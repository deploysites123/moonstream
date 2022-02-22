import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

import web3
from eth_typing import ChecksumAddress
from hexbytes.main import HexBytes
from moonstreamdb.db import yield_db_session_ctx
from moonstreamdb.models import (
    Base,
    EthereumLabel,
    EthereumTransaction,
    PolygonLabel,
    PolygonTransaction,
)
from moonworm.crawler.function_call_crawler import ContractFunctionCall, utfy_dict
from moonworm.crawler.log_scanner import _fetch_events_chunk
from sqlalchemy.orm.session import Session
from tqdm import tqdm
from web3 import Web3
from web3._utils.events import get_event_data

from mooncrawl.data import AvailableBlockchainType  # type: ignore

from ..blockchain import (
    connect,
    get_block_model,
    get_label_model,
    get_transaction_model,
)
from ..moonworm_crawler.db import (
    _event_to_label,
    add_events_to_session,
    commit_session,
    get_last_labeled_block_number,
)
from ..moonworm_crawler.event_crawler import Event, get_block_timestamp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# TODO: ADD VALUE!!!
@dataclass
class FunctionCallWithGasPrice(ContractFunctionCall):
    gas_price: int
    max_fee_per_gas: Optional[int] = None
    max_priority_fee_per_gas: Optional[int] = None


def _function_call_with_gas_price_to_label(
    blockchain_type: AvailableBlockchainType,
    function_call: FunctionCallWithGasPrice,
    label_name: str,
) -> Base:
    """
    Creates a label model.
    """
    label_model = get_label_model(blockchain_type)
    label = label_model(
        label=label_name,
        label_data={
            "type": "tx_call",
            "name": function_call.function_name,
            "caller": function_call.caller_address,
            "args": function_call.function_args,
            "status": function_call.status,
            "gasUsed": function_call.gas_used,
            "gasPrice": function_call.gas_price,
            "maxFeePerGas": function_call.max_fee_per_gas,
            "maxPriorityFeePerGas": function_call.max_priority_fee_per_gas,
        },
        address=function_call.contract_address,
        block_number=function_call.block_number,
        transaction_hash=function_call.transaction_hash,
        block_timestamp=function_call.block_timestamp,
    )

    return label


def add_function_calls_with_gas_price_to_session(
    db_session: Session,
    function_calls: List[FunctionCallWithGasPrice],
    blockchain_type: AvailableBlockchainType,
    label_name: str,
) -> None:

    label_model = get_label_model(blockchain_type)
    transactions_hashes_to_save = [
        function_call.transaction_hash for function_call in function_calls
    ]

    existing_labels = (
        db_session.query(label_model.transaction_hash)
        .filter(
            label_model.label == label_name,
            label_model.log_index == None,
            label_model.transaction_hash.in_(transactions_hashes_to_save),
        )
        .all()
    )

    existing_labels_transactions = [label[0] for label in existing_labels]

    labels_to_save = [
        _function_call_with_gas_price_to_label(
            blockchain_type, function_call, label_name
        )
        for function_call in function_calls
        if function_call.transaction_hash not in existing_labels_transactions
    ]

    logger.info(f"Saving {len(labels_to_save)} labels to session")
    db_session.add_all(labels_to_save)


def _transform_to_w3_tx(
    tx_raw: Union[EthereumTransaction, PolygonTransaction],
) -> Dict[str, Any]:
    """
    Transform db transaction model to web3 transaction
    """
    tx = {
        "blockNumber": tx_raw.block_number,
        "from": tx_raw.from_address,
        "gas": tx_raw.gas,
        "gasPrice": tx_raw.gas_price,
        "hash": HexBytes(tx_raw.hash),
        "input": tx_raw.input,
        "maxFeePerGas": tx_raw.max_fee_per_gas,
        "maxPriorityFeePerGas": tx_raw.max_priority_fee_per_gas,
        "nonce": tx_raw.nonce,
        "to": tx_raw.to_address,
        "transactionIndex": tx_raw.transaction_index,
        "value": tx_raw.value,
    }
    return tx


def process_transaction(
    db_session: Session,
    web3: Web3,
    blockchain_type: AvailableBlockchainType,
    contract: Any,
    secondary_abi: Dict[str, Any],
    transaction: Dict[str, Any],
    blocks_cache: Dict[int, int],
):

    try:
        raw_function_call = contract.decode_function_input(transaction["input"])
        function_name = raw_function_call[0].fn_name
        function_args = utfy_dict(raw_function_call[1])
    except Exception as e:
        # logger.error(f"Failed to decode transaction : {str(e)}")
        selector = transaction["input"][:10]
        function_name = selector
        function_args = "unknown"

    transaction_reciept = web3.eth.getTransactionReceipt(transaction["hash"])

    function_call = FunctionCallWithGasPrice(
        block_number=transaction["blockNumber"],
        block_timestamp=get_block_timestamp(
            db_session,
            web3,
            blockchain_type,
            transaction["blockNumber"],
            blocks_cache,
            100,
        ),
        transaction_hash=transaction["hash"].hex(),
        contract_address=transaction["to"],
        caller_address=transaction["from"],
        function_name=function_name,
        function_args=function_args,
        status=transaction_reciept["status"],
        gas_used=transaction_reciept["gasUsed"],
        gas_price=transaction["gasPrice"],
        max_fee_per_gas=transaction.get(
            "maxFeePerGas",
        ),
        max_priority_fee_per_gas=transaction.get("maxPriorityFeePerGas"),
    )

    secondary_logs = []
    for log in transaction_reciept["logs"]:
        for abi in secondary_abi:
            try:
                raw_event = get_event_data(web3.codec, abi, log)
                event = {
                    "event": raw_event["event"],
                    "args": json.loads(Web3.toJSON(utfy_dict(dict(raw_event["args"])))),
                    "address": raw_event["address"],
                    "blockNumber": raw_event["blockNumber"],
                    "transactionHash": raw_event["transactionHash"].hex(),
                    "logIndex": raw_event["logIndex"],
                }
                secondary_logs.append(_processEvent(event))

                break
            except:
                pass

    return function_call, secondary_logs


def _get_transactions(
    db_session: Session,
    web3: Web3,
    blockchain_type: AvailableBlockchainType,
    transaction_hashes: List[str],
):
    transaction_model = get_transaction_model(blockchain_type)
    transactions = (
        db_session.query(transaction_model)
        .filter(transaction_model.hash.in_(transaction_hashes))
        .all()
    )

    web3_transactions = [
        _transform_to_w3_tx(transaction) for transaction in transactions
    ]

    not_found_transaction_hashes = [
        transaction_hash
        for transaction_hash in transaction_hashes
        if transaction_hash not in [transaction.hash for transaction in transactions]
    ]

    for nf_transaction in not_found_transaction_hashes:
        tx = web3.eth.getTransaction(nf_transaction)

        web3_transactions.append(tx)

    return web3_transactions


def _processEvent(raw_event: Dict[str, Any]):
    event = Event(
        event_name=raw_event["event"],
        args=raw_event["args"],
        address=raw_event["address"],
        block_number=raw_event["blockNumber"],
        block_timestamp=raw_event["blockTimestamp"],
        transaction_hash=raw_event["transactionHash"],
        log_index=raw_event["logIndex"],
    )
    return event


def crawl(
    db_session: Session,
    web3: Web3,
    blockchain_type: AvailableBlockchainType,
    label_name: str,
    abi: Dict[str, Any],
    secondary_abi: Dict[str, Any],
    from_block: int,
    to_block: int,
    addresses: Optional[List[ChecksumAddress]] = None,
    batch_size: int = 100,
) -> None:
    current_block = from_block

    db_blocks_cache = {}
    contract = web3.eth.contract(abi=abi)
    # TODO(yhtiyar): load checkpoint
    events_abi = [item for item in abi if item["type"] == "event"]

    pbar = tqdm(total=(to_block - from_block + 1))
    pbar.set_description(f"Crawling blocks {from_block}-{to_block}")

    while current_block <= to_block:

        batch_end = min(current_block + batch_size, to_block)
        logger.info(f"Crawling blocks {current_block}-{current_block + batch_size}")
        events = []
        logger.info("Fetching events")
        for event_abi in events_abi:
            raw_events = _fetch_events_chunk(
                web3,
                event_abi,
                current_block,
                batch_end,
                addresses,
            )
            for raw_event in raw_events:
                raw_event["blockTimestamp"] = get_block_timestamp(
                    db_session,
                    web3,
                    blockchain_type,
                    raw_event["blockNumber"],
                    blocks_cache=db_blocks_cache,
                    max_blocks_batch=1000,
                )
                event = _processEvent(raw_event)
                events.append(event)

        transaction_hashes = {event.transaction_hash for event in events}
        logger.info(f"Fetched {len(events)} events")
        logger.info(f"Fetching {len(transaction_hashes)} transactions")

        transactions = _get_transactions(
            db_session, web3, blockchain_type, transaction_hashes
        )
        logger.info(f"Fetched {len(transactions)} transactions")

        function_calls = []
        for tx in transactions:
            processed_tx, secondary_logs = process_transaction(
                db_session,
                web3,
                blockchain_type,
                contract,
                secondary_abi,
                tx,
                db_blocks_cache,
            )
            function_calls.append(processed_tx)
            events.extend(secondary_logs)
        add_function_calls_with_gas_price_to_session(
            db_session,
            function_calls,
            blockchain_type,
            label_name,
        )
        add_events_to_session(
            db_session,
            events,
            blockchain_type,
            label_name,
        )
        commit_session(db_session)
        pbar.update(batch_end - current_block + 1)
        current_block = batch_end + 1


def get_checkpoint(
    db_session: Session,
    blockchain_type: AvailableBlockchainType,
    from_block: int,
    to_block: int,
    label_name: str,
) -> int:
    label_model = get_label_model(blockchain_type)
    last_labeled_block = (
        db_session.query(label_model.block_number)
        .filter(label_model.label == label_name)
        .filter(label_model.block_number <= to_block)
        .filter(label_model.block_number >= from_block)
        .order_by(label_model.block_number.desc())
        .first()
    )
    if last_labeled_block is None:
        return from_block
    return last_labeled_block[0] + 1
