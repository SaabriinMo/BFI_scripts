#!/usr/bin/ python3

"""
Script to retrieve folders of
Platform timed text named after
CID Item record object_number.

1. Looks for subfolders in STORAGE path
2. Extract object number from folder name
   and makes list of all files within folder
3. Iterates the enclosed files completing stages:
   a/ Build dictionary for new Item record
   b/ Convert to XML using adlib_v3
   c/ Push data to CID to create item record
   d/ If successful rename file after new CID
      item object_number (forced 01of01) and move
      to autoingest path
4. When all files in a folder processed the
   folder is checked as empty and deleted

NOTES: Updated to work with adlib_v3

2024
"""

import datetime
import logging
import os
import shutil
import sys
from typing import Any, Final, Iterable, Optional, Sequence
import requests

# Local packages
sys.path.append(os.environ["CODE"])
import adlib_v3_sess as adlib
import utils

# Global variables
LOGS: Final = os.environ.get("LOG_PATH")
STORAGE: Final = os.path.join(os.environ.get("QNAP_11"), "timed_text")
AUTOINGEST: Final = os.path.join(
    os.environ.get("AUTOINGEST_QNAP11"), "ingest/autodetect/"
)
CID_API: Final = utils.get_current_api()

# Setup logging
LOGGER = logging.getLogger("document_augmented_filmfund_timed_text")
HDLR = logging.FileHandler(
    os.path.join(LOGS, "document_augmented_filmfund_timed_text.log")
)
FORMATTER = logging.Formatter("%(asctime)s\t%(levelname)s\t%(message)s")
HDLR.setFormatter(FORMATTER)
LOGGER.addHandler(HDLR)
LOGGER.setLevel(logging.INFO)


def cid_check_ob_num(
    object_number: str, session: requests.Session
) -> Optional[Iterable[dict[str, Any]]]:
    """
    Looks up object_number and retrieves title
    and other data for new timed text record
    """
    search: str = f"object_number='{object_number}'"
    hits, record = adlib.retrieve_record(
        CID_API, "items", search, "1", session, fields=None
    )
    if hits is None:
        raise Exception(f"CID API was unreachable for Items search: {search}")
    if hits == 0:
        return None
    return record


def walk_folders(storage: str) -> list[str]:
    """
    Collect list of folderpaths
    for files named rename_<platform>
    """
    print(storage)
    timed_text_folders = []
    for root, dirs, _ in os.walk(storage):
        for directory in dirs:
            timed_text_folders.append(os.path.join(root, directory))
    print(f"{len(timed_text_folders)} rename folder(s) found")

    return timed_text_folders


def main():
    """
    Search for folders named after CID item records
    Check for contents and create new CID item record
    for each timed text within. Rename and move for ingest.
    """
    if not utils.check_control("power_off_all"):
        LOGGER.info("Script run prevented by downtime_control.json. Script exiting.")
        sys.exit("Script run prevented by downtime_control.json. Script exiting.")
    if not utils.check_storage(STORAGE):
        LOGGER.info("Script run prevented by storage_control.json. Script exiting.")
        sys.exit("Script run prevented by storage_control.json. Script exiting.")
    if not utils.cid_check(CID_API):
        LOGGER.critical("* Cannot establish CID session, exiting script")
        sys.exit("* Cannot establish CID session, exiting script")

    folder_list: list[str] = walk_folders(STORAGE)
    if len(folder_list) == 0:
        sys.exit("No folders found at this time.")

    LOGGER.info("== Document augmented Film Fund timed text start ===================")
    session: requests.Session = adlib.create_session()
    for fpath in folder_list:
        print(fpath)
        if not utils.check_control("pause_scripts"):
            LOGGER.info(
                "Script run prevented by downtime_control.json. Script exiting."
            )
            sys.exit("Script run prevented by downtime_control.json. Script exiting.")
        if not os.path.exists(fpath):
            LOGGER.warning("Folder path is not valid: %s", fpath)
            continue
        object_number: str = os.path.basename(fpath)
        file_list: list[str] = os.listdir(fpath)
        if not file_list:
            LOGGER.warning("Skipping. No files found in folderpath: %s", fpath)
            continue
        LOGGER.info(
            "Files found in target folder %s: %s", object_number, ", ".join(file_list)
        )

        # Check object number valid
        record: Optional[Iterable[dict[str, Any]]] = cid_check_ob_num(
            object_number, session
        )
        print(record)
        if record is None:
            LOGGER.warning("Skipping: Record could not be matched with object_number")
            continue

        priref: str = adlib.retrieve_field_name(record[0], "priref")[0]
        print(f"Priref matched with retrieved folder name: {priref}")
        LOGGER.info("Priref matched with folder name: %s", priref)

        # Create CID item record for each timed text in folder
        for file in file_list:
            if file.lower().endswith(".md5"):
                continue
            print(f"File found: {file}")
            ext = file.split(".")[-1]
            item_record = create_new_item_record(priref, file, record, session)
            if item_record is None:
                continue

            tt_priref: str = adlib.retrieve_field_name(item_record, "priref")[0]
            tt_ob_num: str = adlib.retrieve_field_name(item_record, "object_number")[0]
            LOGGER.info("** CID Item record created: %s", tt_priref)
            print(f"CID Item record created: {tt_priref}, {tt_ob_num}")

            # Rename file to new filename from object-number
            new_fname: str = f"{tt_ob_num.replace('-', '_')}_01of01.{ext}"
            new_fpath: str = os.path.join(fpath, new_fname)
            LOGGER.info("%s to be renamed %s", file, new_fname)
            rename_success = rename_or_move(
                "rename", os.path.join(fpath, file), new_fpath
            )
            if rename_success is False:
                LOGGER.warning("Unable to rename file: %s", os.path.join(fpath, file))
            elif rename_success is True:
                LOGGER.info("File successfully renamed. Moving to autoingest path")
            elif rename_success == "Path error":
                LOGGER.warning("Path error: %s", os.path.join(fpath, file))

            # Move file to new autoingest path
            move_success = rename_or_move(
                "move", new_fpath, os.path.join(AUTOINGEST, new_fname)
            )
            if move_success is False:
                LOGGER.warning(
                    "Error with file move to autoingest, leaving in place for manual assistance"
                )
            elif move_success is True:
                LOGGER.info(
                    "File successfully moved to autoingest path: %s\n", AUTOINGEST
                )
            elif move_success == "Path error":
                LOGGER.warning("Path error: %s", new_fpath)

        # Check fpath is empty and delete
        if len(os.listdir(fpath)) == 0:
            LOGGER.info("All files processed in folder: %s", object_number)
            LOGGER.info("Deleting empty folder: %s", fpath)
            os.rmdir(fpath)
        else:
            LOGGER.warning(
                "Leaving folder %s in place as files still remaining in folder %s",
                object_number,
                os.listdir(fpath),
            )

    LOGGER.info(
        "== Document augmented Film Fund timed text end =====================\n"
    )


def build_record_defaults(platform: str) -> Iterable[dict[str, str]]:
    """
    Return all record defaults
    """
    record = [
        {"input.name": "datadigipres"},
        {"input.date": str(datetime.datetime.now())[:10]},
        {"input.time": str(datetime.datetime.now())[11:19]},
        {
            "input.notes": f"{platform} metadata integration - automated bulk documentation for timed text"
        },
    ]

    return record


def rename_or_move(arg: str, file_a: str, file_b: str) -> str | bool:
    """
    Use shutil or os to move/rename
    from file a to file b. Verify change
    before confirming success/failure
    """

    if not os.path.isfile(file_a):
        return "Path error"

    if arg == "move":
        try:
            shutil.move(file_a, file_b)
        except Exception as err:
            LOGGER.warning(
                "rename_or_move(): Failed to %s file to new destination: \n%s\n%s",
                arg,
                file_a,
                file_b,
            )
            print(err)
            return False

    if arg == "rename":
        try:
            os.rename(file_a, file_b)
        except Exception as err:
            LOGGER.warning(
                "rename_or_move(): Failed to %s file to new destination: \n%s\n%s",
                arg,
                file_a,
                file_b,
            )
            print(err)
            return False

    if os.path.isfile(file_b):
        return True
    return False


def make_item_record_dict(priref, file, record):
    """
    Get CID item record for source and borrow data
    for creation of new CID item record
    """
    ext = file.split(".")[-1]
    if "Acquisition_source" in str(record):
        platform = adlib.retrieve_field_name(record[0], "acquisition.source")[0]
        record_default = build_record_defaults(platform)
        if not platform:
            platform = ""
    else:
        platform = ""
        record_default = build_record_defaults("Film Fund")

    item = []
    item.extend(record_default)
    item.append({"record_type": "ITEM"})
    item.append({"item_type": "DIGITAL"})
    item.append({"copy_status": "M"})
    item.append({"copy_usage.lref": "131560"})
    item.append({"accession_date": str(datetime.datetime.now())[:10]})

    if "Title" in str(record):
        ff_title = adlib.retrieve_field_name(record[0], "title")[0]
        item.append({"title": f"{ff_title} (Timed Text)"})
        if "title_article" in str(record[0]):
            item.append(
                {
                    "title.article": adlib.retrieve_field_name(
                        record[0], "title_article"
                    )[0]
                }
            )
        item.append({"title.language": "English"})
        item.append({"title.type": "05_MAIN"})
    else:
        LOGGER.warning("No title data retrieved. Aborting record creation")
        return None
    if "Part_of" in str(record):
        parent_priref = adlib.retrieve_field_name(
            record[0]["Part_of"][0]["part_of_reference"][0], "priref"
        )[0]
        item.append({"part_of_reference.lref": parent_priref})
    else:
        LOGGER.warning("No part_of_reference data retrieved. Aborting record creation")
        return None
    item.append({"related_object.reference.lref": priref})
    item.append({"related_object.notes": "Timed text for"})
    if len(ext) > 1:
        item.append({"file_type": ext.upper()})
    if "acquisition.date" in str(record):
        item.append(
            {
                "acquisition.date": adlib.retrieve_field_name(
                    record[0], "acquisition.date"
                )[0]
            }
        )
    if "acquisition.method" in str(record):
        item.append(
            {
                "acquisition.method": adlib.retrieve_field_name(
                    record[0], "acquisition.method"
                )[0]
            }
        )
    if len(platform) > 0:
        item.append({"acquisition.source": platform})
        item.append({"acquisition.source.type": "DONOR"})
    item.append(
        {
            "access_conditions": "Access requests for this collection are subject to an approval process. "
            "Please raise a request via the Collections Systems Service Desk, describing your specific use."
        }
    )
    item.append({"access_conditions.date": str(datetime.datetime.now())[:10]})
    if "grouping" in str(record):
        item.append({"grouping": adlib.retrieve_field_name(record[0], "grouping")[0]})
    item.append({"language": "English"})
    item.append({"language.type": "TIMTEXT"})
    if len(file) > 1:
        item.append({"digital.acquired_filename": file})
        item.append({"digital.acquired_filename.type": "FILE"})

    return item


def create_new_item_record(
    priref: str,
    fname: str,
    record: Optional[Iterable[dict[str, Any]]],
    session: requests.Session,
) -> Optional[str]:
    """
    Build new CID item record from existing data and make CID item record
    """

    item_dct = make_item_record_dict(priref, fname, record)
    print(item_dct)
    item_xml = adlib.create_record_data(CID_API, "items", session, "", item_dct)
    print(item_xml)
    LOGGER.info(item_xml)
    new_record = adlib.post(CID_API, item_xml, "items", "insertrecord", session)
    if new_record is None:
        LOGGER.warning("Skipping: CID item record creation failed: %s", item_xml)
        return None
    LOGGER.info("New CID item record created: %s", new_record)
    return new_record


if __name__ == "__main__":
    main()
