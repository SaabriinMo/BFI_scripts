#!/usr/bin/ python3

"""
Script to look for files named 'EDIT_{source_item}',
create new CID item record with VIEW specifics, rename
file then move to autoingest path

NOTES: Integrated with adlib_v3 for test

2024
"""

import datetime
import logging

# Public packages
import os
import shutil
import sys
from typing import Any, Final, Optional

# Local packages
sys.path.append(os.environ["CODE"])
import adlib_v3 as adlib
import utils

# Global variables
INGEST: Final = os.path.join(os.environ.get("BP_DIGITAL"), "autoingest/")
STORAGE: Final = os.path.join(INGEST, "access_edits")
LOCAL_LOG: Final = os.path.join(STORAGE, "access_edits_renamed.log")
AUTOINGEST: Final = os.path.join(INGEST, "ingest/autodetect")
LOGS: Final = os.environ.get("LOG_PATH")
CONTROL_JSON: Final = os.path.join(LOGS, "downtime_control.json")
CID_API: Final = utils.get_current_api()

# Setup loggin
LOGGER = logging.getLogger("document_access_edits")
HDLR = logging.FileHandler(os.path.join(LOGS, "document_access_edits.log"))
FORMATTER = logging.Formatter("%(asctime)s\t%(levelname)s\t%(message)s")
HDLR.setFormatter(FORMATTER)
LOGGER.addHandler(HDLR)
LOGGER.setLevel(logging.INFO)


def process_duplicate_files(fname: str) -> Optional[str]:
    """
    Check if a given filepath is inside the log file (access_document_edit.log)
    and move to folder if it's inside the log.
    """
    # go through the file
    if not os.path.exists(LOCAL_LOG):
        return "local log does not exist"

    with open(LOCAL_LOG, "r") as log:
        contents = log.readlines()

    # check if the file is inside the log
    for row in contents:
        if fname in str(row):
            if os.path.exists(os.path.join(STORAGE, f"duplicates/{fname}")):
                os.remove(os.path.join(STORAGE, f"duplicates/{fname}"))
            try:
                shutil.move(
                    os.path.join(STORAGE, fname),
                    os.path.join(STORAGE, f"duplicates/{fname}"),
                )
                local_log(f"** Duplicated file has been found: {fname} \n")
                return "duplicated file"
            except Exception as e:
                print(e)
                raise Exception from e

    return "new file"


def get_source_record(file: str) -> Optional[list[dict[str, str]]]:
    """
    Get source Item record ob_num from filename
    """

    source_ob_num = file.split("EDIT_")[1].split(".")[0]
    search: str = f"object_number='{source_ob_num}'"
    hits, record = adlib.retrieve_record(CID_API, "items", search, "0")
    if hits is None:
        raise Exception(f"CID API was unreachable for Items search: {search}")
    if hits == 0:
        return None
    return record


def main():
    """
    Iterate access_edits folder working through edited
    files prefixed 'EDIT_'
    """
    if not utils.check_storage(STORAGE):
        LOGGER.info("Script run prevented by storage_control.json. Script exiting.")
        sys.exit("Script run prevented by storage_control.json. Script exiting.")

    file_list = [x for x in os.listdir(STORAGE) if x.startswith("EDIT_")]
    if len(file_list) == 0:
        sys.exit()

    LOGGER.info("======== Document Access Edits scripts start =====================")
    for file in file_list:
        if not utils.check_control("pause_scripts"):
            LOGGER.info(
                "Script run prevented by downtime_control.json. Script exiting."
            )
            sys.exit("Script run prevented by downtime_control.json. Script exiting.")
        if not utils.cid_check(CID_API):
            LOGGER.critical("* Cannot establish CID session, exiting script")
            sys.exit("* Cannot establish CID session, exiting script")

        if not utils.check_storage(file):
            LOGGER.info(
                "Storage check failed for %s. Please check storage is available.",
                fullpath,
            )
            sys.exit("Storage check failed. Please check storage is available.")
        fpath = os.path.join(STORAGE, file)
        LOGGER.info("File found to process: %s", fpath)
        if not os.path.isfile(fpath):
            LOGGER.warning("Skipping: File type has not been recoginsed.")
            continue
        result = process_duplicate_files(file)
        if result == "duplicated file":
            LOGGER.warning("DigiOps supplied a duplicate filename - replacing %s", file)
            continue
        # Get source Item record ob_num from filename
        source_record = get_source_record(file)
        if source_record is None:
            LOGGER.warning(
                "Skipping: Unable to match source object number %s to CID item record",
                file,
            )
            continue
        source_priref = adlib.retrieve_field_name(source_record[0], "priref")[0]

        # Create new Item record and append quality comments
        print("Going to create new record!")
        new_record = create_new_item_record(source_priref, file, source_record)
        if new_record is None:
            continue
        priref = adlib.retrieve_field_name(new_record, "priref")[0]
        ob_num = adlib.retrieve_field_name(new_record, "object_number")[0]
        if ob_num is None:
            ob_num = ""
        LOGGER.info("** New CID Item record created %s - %s", priref, ob_num)

        comments = """Viewing copy created from digital master which has been ingested for access instances. The file may have had adverts, bars and tones cut out, or other fixes applied."""
        success = adlib.add_quality_comments(CID_API, priref, comments)
        if not success:
            LOGGER.warning("Quality comments were not written to record: %s", priref)
        LOGGER.info("Quality comments added to CID item record %s", priref)

        new_fname = f"{ob_num.replace('-', '_')}_01of01.{file.split('.')[-1]}"
        new_fpath = os.path.join(AUTOINGEST, new_fname)
        LOGGER.info("Renaming file:\n%s\n%s", fpath, new_fpath)
        local_log(f"Edit file: {fpath}")
        local_log(f"Renamed to: {new_fpath}")
        os.rename(fpath, new_fpath)
        if os.path.isfile(new_fpath):
            LOGGER.info("New file successfully renamed and moved to autoingest path")
        else:
            LOGGER.warning("Failed to rename/move file: %s", fpath)

    LOGGER.info("======== Document Access Edits scripts end =======================")


def create_new_item_record(
    source_priref: Optional[str], file: str, source_record: list[dict[str, str]]
) -> Optional[dict[Any, Any]]:
    """
    Build new CID item record from existing data and make CID item record
    """
    item_dct = make_item_record_dict(source_priref, file, source_record[0])
    LOGGER.info(item_dct)
    item_xml = adlib.create_record_data(CID_API, "items", "", item_dct)
    new_record = adlib.post(CID_API, item_xml, "items", "insertrecord")
    if new_record is None:
        LOGGER.warning("Skipping: CID item record creation failed: %s", item_xml)
        return None
    LOGGER.info("New CID item record created: %s", new_record)
    return new_record


def make_item_record_dict(
    priref: Optional[str], file: str, record: str
) -> Optional[list[dict[str, str]]]:
    """
    Get CID item record for source and borrow data
    for creation of new CID item record
    """
    ext = file.split(".")[-1].upper()

    item = []
    item.extend(defaults())
    if isinstance(priref, list):
        priref = priref[0]

    if "Title" in str(record):
        title = adlib.retrieve_field_name(record, "title")[0]
        item.append({"title": title})
        if "title.article" in str(record):
            item.append(
                {"title.article": adlib.retrieve_field_name(record, "title.article")[0]}
            )
        item.append({"title.language": "English"})
        item.append({"title.type": "05_MAIN"})
    else:
        LOGGER.warning("No title data retrieved. Aborting record creation")
        return None
    if "part_of_reference" in str(record):
        item.append(
            {
                "part_of_reference.lref": adlib.retrieve_field_name(
                    record["Part_of"][0]["part_of_reference"][0], "priref"
                )[0]
            }
        )
    else:
        LOGGER.warning("No part_of_reference data retrieved. Aborting record creation")
        return None
    if "grouping.lref" in str(record):
        item.append(
            {"grouping.lref": adlib.retrieve_field_name(record, "grouping.lref")[0]}
        )
    if "language" in str(record):
        item.append({"language": adlib.retrieve_field_name(record, "language")[0]})
        item.append(
            {"language.type": adlib.retrieve_field_name(record, "language.type")[0]}
        )

    item.append({"digital.acquired_filename": file})
    item.append({"digital.acquired_filename.type": "FILE"})
    item.append({"file_type": ext})
    item.append({"scan.type": "PROGRESSIVE"})
    item.append({"source_item.lref": priref})
    print(f"Item record assembled:\n{item}")
    return item


def defaults() -> list[dict[Any, Any]]:
    """
    Build defaults for new CID item records
    """
    record = [
        {"input.name": "datadigipres"},
        {"input.date": str(datetime.datetime.now())[:10]},
        {"input.time": str(datetime.datetime.now())[11:19]},
        {"input.notes": "DMS access edit integration - automated bulk documentation"},
        {"record_access.user": "BFIiispublic"},
        {"record_access.rights": "0"},
        {"record_access.reason": "SENSITIVE_LEGAL"},
        {"language.lref": "74129"},
        {"language.type": "DIALORIG"},
        {"record_type": "ITEM"},
        {"item_type": "DIGITAL"},
        {"copy_status": "V"},
        {"copy_usage.lref": "131560"},
        {"creator.lref": "999570701"},
        {"creator.role.lref": "75250"},
        {
            "access_conditions": "Before reusing BFI National Archive digital collections please ensure the required clearances from copyright holders, contributors or other stakeholders have been obtained for specific use."
        },
        {"access_conditions.date": str(datetime.datetime.now())[:10]},
    ]

    return record


def local_log(data: str) -> None:
    """
    Write collected data actions list of items
    to local log in audio_operations
    """
    if len(data) > 0:
        with open(LOCAL_LOG, "a+") as log:
            log.write(f"{str(datetime.datetime.now())[0:16]}: {data}\n")
            log.close()


if __name__ == "__main__":
    main()
