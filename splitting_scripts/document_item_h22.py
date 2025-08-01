#!/usr/bin/env python3

"""
Called by splitting scripts
Refactored to Py3
June 2022
"""

import datetime

# Public packages
import os
import sys
from typing import Any, Final, Optional

# Private packages
sys.path.append(os.environ["CODE"])
import adlib_v3 as adlib
import utils

# Configure adlib
CID_API: Final = utils.get_current_api()
CODE_PATH: Final = os.environ["CODE"]


def log_print(data: str) -> None:
    """
    Temp func to track failures in
    CID item record creation
    """
    with open(
        os.path.join(CODE_PATH, "splitting_scripts/temp_logs/h22_item_records.log"), "a"
    ) as file:
        file.write(f"{datetime.datetime.now().isoformat()}\n")
        file.write(f"{data}\n")
        file.write("--------------------------------\n")


def fetch_existing_object_number(source_object_number: str) -> str:
    """Retrieve the Object Number for an existing MKV record, for use in renaming
    the existing Matroska (single Item) or naming the segment"""

    search = (
        f'(file_type=MKV and source_item->(object_number="{source_object_number}"))'
    )
    hits, record = adlib.retrieve_record(
        CID_API, "items", search, "1", ["object_number"]
    )
    if hits is None:
        raise Exception("Unable to retrieve data from Item record")
    if hits > 0:
        derived_object_number = adlib.retrieve_field_name(record[0], "object_number")[0]
        return derived_object_number
    else:
        raise Exception("Unable to retrieve data from Item record")


def new_or_existing(
    source_object_number, segments, duration, extension, note=None
) -> str:
    """Create a new item record for multi-reeler if one doesn't already exist,
    otherwise return the ID of the existing record"""

    hits, record = already_exists(source_object_number)
    if hits is None:
        raise Exception("Unable to retrieve data from Item record")
    elif hits == 1:
        destination_object = adlib.retrieve_field_name(record, "object_number")[0]
        log_print(f"new_or_existing(): Found CID item record - {destination_object}")
        return destination_object
    elif hits > 1:
        log_print(f"new_or_existing(): Multiple records found {record}")
        return None
        # Append segmentation information
        # Increment total item duration
    elif hits == 0:
        # Create new
        log_print(
            f"new_or_existing(): No record found {source_object_number}, creating new one"
        )
        destination_object = new(
            source_object_number, segments, duration, extension, note
        )
        return destination_object


def already_exists(source_object_number) -> tuple[int,]:
    """Has an MKV record already been created for source?"""

    search = f'(grouping.lref=398385 and source_item->(object_number="{source_object_number}"))'
    hits, record = adlib.retrieve_record(CID_API, "items", search, "0")
    if hits is None:
        raise Exception("Unable to retrieve data from Item record")
    elif hits >= 1:
        log_print(f"already_exists(): {record}")
        return hits, record[0]
    else:
        return hits, None


def new(
    source_object_number: str,
    segments: list[str],
    duration: int,
    extension: str,
    note=None,
):
    """Create a new item record"""

    # Fetch source item data
    search = f'object_number="{source_object_number}"'
    hits, record = adlib.retrieve_record(CID_API, "items", search, "1")
    if hits is None:
        raise Exception("Unable to retrieve data from Item record")
    elif hits > 0:
        source_lref = int(adlib.retrieve_field_name(record[0], "priref")[0])
    if "title" in str(record):
        title = adlib.retrieve_field_name(record[0], "title")[0]
    if not title:
        return None
    if "part_of_reference" in str(record):
        parent_priref = adlib.retrieve_field_name(
            record[0]["Part_of"][0]["part_of_reference"][0], "priref"
        )[0]
    if not parent_priref:
        return None

    # Construct new record
    rec = [
        {"record_type": "ITEM"},
        {"item_type": "DIGITAL"},
        {"copy_status": "M"},
        {"copy_usage": "Restricted access to preserved digital file"},
        {"file_type": extension.upper()},
        {"grouping.lref": "398385"},
        {"input.name": "datadigipres"},
        {"input.date": datetime.datetime.now().isoformat()[:10]},
        {"input.time": datetime.datetime.now().isoformat()[11:].split(".")[0]},
        {"source_item.lref": str(source_lref)},
        {"source_item.content": "IMAGE_SOUND"},
        {"part_of_reference.lref": str(parent_priref)},
        {"title": title},
        {"title.type": "10_ARCHIVE"},
    ]

    # Append duration if given
    if duration:
        # string_duration = time.strftime('%H:%M:%S', time.gmtime(int(duration)))
        rec.append({"video_duration": str(duration)})

    # Append segmentation data
    for t in segments:
        rec.append({"video_part": f"{t[0]}-{t[1]}"})

    # Input note if given
    if note is not None:
        rec.append({"input.notes": note})

    rec_xml = adlib.create_record_data(CID_API, "items", "", rec)
    new_record = adlib.post(CID_API, rec_xml, "items", "insertrecord")
    if new_record:
        try:
            new_object = adlib.retrieve_field_name(new_record, "object_number")[0]
            log_print(
                f"new(): New record created: {new_object} for source object {source_object_number}"
            )
            return new_object
        except Exception as exc:
            raise Exception("Failed to retrieve new Object Number") from exc

    else:
        raise Exception("Error creating record")
