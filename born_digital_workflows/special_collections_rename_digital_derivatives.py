#!/usr/bin/env python3

"""
Special Collections Digital Derivative script
Creation of Analogue and Digital Item records

Script stages:
1. Searches STORAGE folder collecting list of 'works' folders
2. Iterates these works folders completing following steps:
    a. Extracts work data from folder name
    b. Gets list of image files within 'works' folder
    c. Iterates image files, skips if not accepted image extension
    d. For every image creates a CID Analogue image record,
       extracts priref/object number and links to work via related_object.reference
    e. Uses CID analogue object number to create CID Digital item record,
       linked to analogue record via source_item, and to work via related_object.reference
    f. Uses CID Digital item record object_number to rename the image file
    g. Moves renamed file to local autoingest path
    h. If any CID record creation fails the file is skipped and left in place
3. Checks if the 'works' folder is empty, and if so deletes empty folder
4. Continues iteration until all 'works' have been processed.

Notes:
Uses requests.Sessions() for creation of works
within on session. Trial of sessions().

2024
"""

import datetime
import logging
import os
import shutil
import sys
from typing import Final, Optional
import requests

# Private packages
sys.path.append(os.environ["CODE"])
import adlib_v3_sess as adlib
import utils

# Global path variables
SCPATH = os.environ["SPECIAL_COLLECTIONS"]
STORAGE = os.path.join(SCPATH, "Uncatalogued_stills_digitial_derivative/")
AUTOINGEST = os.path.join(os.environ["AUTOINGEST_IS_SPEC"], "ingest/proxy/image/")
LOG = os.path.join(
    os.environ["LOG_PATH"], "special_collections_rename_digital_derivatives.log"
)
MEDIAINFO_PATH = os.path.join(os.environ["LOG_PATH"], "cid_mediainfo/")
CID_API = os.environ["CID_API3"]
# CID_API = utils.get_current_api()

LOGGER = logging.getLogger("sc_rename_digital_derivatives")
HDLR = logging.FileHandler(LOG)
FORMATTER = logging.Formatter("%(asctime)s\t%(levelname)s\t%(message)s")
HDLR.setFormatter(FORMATTER)
LOGGER.addHandler(HDLR)
LOGGER.setLevel(logging.INFO)

BIT_DEPTHS = {
    "8": "401572",
    "10": "99796",
    "12": "392421",
    "16": "99797",
    "24": "395618",
    "32": "99838",
    "48": "95709",
}


def cid_retrieve(
    fname: str, session: requests.Session
) -> Optional[tuple[str, str, str, str, str, str]]:
    """
    Receive filename and search in CID works dB
    Return selected data to main()
    """
    search: str = f'object_number="{fname}"'
    fields: list[str] = [
        "priref",
        "object_number",
        "title_date_start",
        "title_date.type",
        "title",
        "title.article",
    ]

    record = adlib.retrieve_record(CID_API, "works", search, "1", session, fields)[1]
    LOGGER.info("cid_retrieve(): Making CID query request with:\n%s", search)
    if not record:
        print(f"cid_retrieve(): Unable to retrieve data for {fname}")
        utils.logger(
            LOG, "exception", f"cid_retrieve(): Unable to retrieve data for {fname}"
        )
        return None

    if "priref" in str(record):
        priref = adlib.retrieve_field_name(record[0], "priref")[0]
    else:
        priref = ""
    if "object_number" in str(record):
        ob_num = adlib.retrieve_field_name(record[0], "object_number")[0]
    else:
        ob_num = ""
    if "Title" in str(record):
        title = adlib.retrieve_field_name(record[0], "title")[0]
    else:
        title = ""
    if "title.article" in str(record):
        title_article = adlib.retrieve_field_name(record[0], "title.article")[0]
    else:
        title_article = ""
    if "title_date_start" in str(record):
        title_date_start = adlib.retrieve_field_name(record[0], "title_date_start")
    else:
        title_date_start = []
    if "title_date.type" in str(record):
        title_date_type = adlib.retrieve_field_name(record[0], "title_date.type")
    else:
        title_date_type = []

    tds = sort_date_types(title_date_start, title_date_type)
    return priref, ob_num, title, title_article, tds


def sort_date_types(
    title_date_start: list[str], title_date_type: list[str]
) -> Optional[str]:
    """
    Make sure only 'copyright' pair returned
    """
    if len(title_date_start) != len(title_date_type):
        return None
    if "Copyright" not in str(title_date_type):
        return None

    idx = title_date_start.index("Copyright")

    if isinstance(idx, int):
        return title_date_start[idx]
    return None


def main():
    """
    Iterate folders in STORAGE, find image files in folders
    named after work and create analogue/digital item records
    for every photo. Clean up empty folders.
    """
    if not utils.check_control("power_off_all"):
        LOGGER.info("Script run prevented by downtime_control.json. Script exiting.")
        sys.exit("Script run prevented by downtime_control.json. Script exiting.")

    if not utils.cid_check(CID_API):
        sys.exit("* Cannot establish CID session, exiting script")

    if not utils.check_storage(STORAGE):
        LOGGER.info("Script run prevented by storage_control.json. Script exiting.")
        sys.exit("Script run prevented by storage_control.json. Script exiting.")

    LOGGER.info(
        "=========== Special Collections rename - Digital Derivatives START ============"
    )
    print(STORAGE)

    work_directories = [
        x for x in os.listdir(STORAGE) if os.path.isdir(os.path.join(STORAGE, x))
    ]
    session = adlib.create_session()
    print(work_directories)
    for work in work_directories:
        if not utils.check_control("pause_scripts"):
            sys.exit("Script run prevented by downtime_control.json. Script exiting.")
        wpath = os.path.join(STORAGE, work)
        LOGGER.info("Work folder found: %s", work)
        work_data = cid_retrieve(work, session)
        if work_data is None:
            LOGGER.warning("Please check folder name %s as no CID match found", work)
            continue
        print(work_data)

        # Build file list of wpath contents
        images = [
            x for x in os.listdir(wpath) if os.path.isfile(os.path.join(wpath, x))
        ]
        sorted_images = sorted(images)
        for image in sorted_images:
            if not image.endswith(
                (".tiff", ".tif", ".TIFF", ".TIF", ".jpeg", ".jpg", ".JPEG", ".JPG")
            ):
                LOGGER.warning(
                    "Skipping: File found in folder %s that is not image file: %s",
                    work,
                    image,
                )
                continue
            LOGGER.info("Processing image file: %s", image)
            ipath = os.path.join(wpath, image)

            if bool(utils.check_filename(image)):
                LOGGER.warning(
                    "Skipping: File passed filename checks and likely already renumbered: %s",
                    image,
                )
                ob_num = utils.get_object_number(image)
                if not ob_num:
                    continue
                rec = adlib.retrieve_record(
                    CID_API, "internalobject", f'object_number="{ob_num}"', "1", session
                )[1]
                check = adlib.retrieve_field_name(rec[0], "digital.born_or_derived")[0]
                if "DIGITAL_DERIVATIVE_PRES" in check:
                    LOGGER.info(
                        "Moving to autoingest. File renumbered to matching Digital record: %s",
                        ob_num,
                    )
                    print(f"move({ipath}, 'ingest')")
                continue

            # Analogue and Digital Derivative records to be made
            record_analogue = build_defaults(work_data, ipath, image, "analogue")[0]
            analogue_priref, analogue_obj = create_new_image_record(
                record_analogue, session
            )
            LOGGER.info(
                "* New Item record created for image %s Analogue %s",
                image,
                analogue_priref,
            )

            record_digital, metadata = build_defaults(
                work_data, ipath, image, "digital", analogue_obj
            )
            digi_priref, digi_obj = create_new_image_record(record_digital, session)
            LOGGER.info(
                "* New Item record created for image %s Digital Derivative %s",
                image,
                digi_priref,
            )

            if len(analogue_priref) == 0 or len(digi_priref) == 0:
                LOGGER.warning(
                    "Missing priref following record creation for %s. Analogue priref %s / Digital priref %s",
                    image,
                    analogue_priref,
                    digi_priref,
                )
                LOGGER.warning(
                    "Moving file to failure folder. Manual clean up of records required."
                )
                move(ipath, "fail")
                continue

            if len(digi_obj) > 0:
                # Append metadata to header tags
                if len(metadata) > 0:
                    header = f"<Header_tags><header_tags.parser>Exiftool</header_tags.parser><header_tags><![CDATA[{metadata}]]></header_tags></Header_tags>"
                    success = write_payload(digi_priref, header, session)
                    if not success:
                        LOGGER.warning(
                            "Payload data was not written to CID record: %s\n%s",
                            digi_priref,
                            metadata,
                        )

                LOGGER.info(
                    "** Renumbering file %s with object number %s", image, digi_obj
                )
                new_filepath, new_file = rename(ipath, digi_obj)
                if os.path.exists(new_filepath):
                    LOGGER.info("New filename generated: %s", new_file)
                    LOGGER.info(
                        "File renumbered and filepath updated to: %s", new_filepath
                    )
                    success = move(new_filepath, "ingest")
                    if success:
                        LOGGER.info(
                            "File %s relocated to Autoingest %s",
                            new_file,
                            str(datetime.datetime.now())[:19],
                        )
                    else:
                        LOGGER.warning(
                            "FILE %s DID NOT MOVE SUCCESSFULLY TO AUTOINGEST", new_file
                        )
                else:
                    LOGGER.warning("Problem creating new number for %s", image)
                success = write_exif_to_file(new_file, metadata)
                if not success:
                    LOGGER.warning(
                        "Unable to create EXIF metadata file for image: %s\n%s",
                        image,
                        metadata,
                    )
            else:
                LOGGER.warning(
                    "Object number was not returned following creation of CID Item record for digital derivative."
                )
                continue

        # Checking all processed and delete empty folder
        folder_empty = os.listdir(wpath)
        if len(folder_empty) == 0:
            LOGGER.info("All files in folder processed. Deleting folder: %s", work)
            os.rmdir(wpath)
        else:
            LOGGER.warning(
                "Not all items in folder processed, leaving folder in place for repeat attempt."
            )
            continue

    LOGGER.info(
        "=========== Special Collections rename - Digital Derivatives END =============="
    )


def build_defaults(
    work_data: Optional[tuple[str, str, str, str, str, str]],
    ipath: str,
    image: str,
    arg: str,
    obj=None,
) -> Optional[tuple[list[dict[str, str]], Optional[str]]]:
    """
    Build up item record defaults
    """
    metadata = None
    records = [
        {"institution.name.lref": "999570701"},
        {"object_type": "OBJECT"},
        {"description_level_object": "STILLS"},
        {"object_category.lref": "132885"},
    ]
    print(work_data)
    if work_data[1]:
        records.append({"related_object.reference.lref": work_data[0]})
    else:
        LOGGER.warning("No parent object number retrieved. Script exiting.")
        return None
    if work_data[2]:
        records.append({"title": work_data[2]})
    else:
        LOGGER.warning("No title data retrieved. Script exiting.")
        return None
    if work_data[3]:
        records.append({"title.article": work_data[3]})
    if work_data[4]:
        records.append({"production.date.start": work_data[4]})

    if arg == "analogue":
        records.append({"analogue_or_digital": "ANALOGUE"})
    elif arg == "digital":
        records.append({"analogue_or_digital": "DIGITAL"})
        records.append({"digital.born_or_derived": "DIGITAL_DERIVATIVE_PRES"})
        records.append({"digital.acquired_filename": image})
        if obj:
            records.append({"source_item": obj})
        ext = image.split(".")[-1]
        if ext.lower() in ["jpeg", "jpg"]:
            records.append({"file_type.lref": "396310"})
        elif ext.lower() in ["tif", "tiff"]:
            records.append({"file_type.lref": "395395"})
        bitdepth = utils.get_metadata("Image", "BitDepth", ipath)
        if bitdepth:
            for key, val in BIT_DEPTHS.items():
                if bitdepth == key:
                    records.append({"bit_depth.lref": val})
        metadata_rec, metadata = get_exifdata(ipath)
        if metadata_rec:
            print(metadata_rec)
            records.extend(metadata_rec)

    records.append({"input.name": "datadigipres"})
    records.append({"input.date": str(datetime.datetime.now())[:10]})
    records.append({"input.time": str(datetime.datetime.now())[11:19]})
    records.append(
        {
            "input.notes": "Automated record creation for Special Collections, to facilitate ingest to DPI"
        }
    )
    print(records)
    return records, metadata


def get_exifdata(dpath: str) -> tuple[Optional[list[dict[str, str]]], Optional[str]]:
    """
    Attempt to get metadata for record build
    Example dict below, waiting for confirmation
    """
    metadata: list[dict[str, str]] = []
    creator_data: list[str] = []
    rights_data: list[str] = []
    data: str = utils.exif_data(dpath)
    print(data)
    if not data:
        return None, None
    data_list = data.split("\n")
    for d in data_list:
        if d.startswith("File Size "):
            val = d.split(": ", 1)[-1]
            metadata.append({"filesize": val.split(" ")[0]})
            metadata.append({"filesize.unit": val.split(" ")[-1]})
        elif d.startswith("Image Height "):
            metadata.append({"dimension.type": "Height"})
            metadata.append({"dimension.value": d.split(": ", 1)[-1]})
            metadata.append({"dimension.unit": "Pixels"})
        elif d.startswith("Image Width "):
            metadata.append({"dimension.type": "Width"})
            metadata.append({"dimension.value": d.split(": ", 1)[-1]})
            metadata.append({"dimension.unit": "Pixels"})
        elif d.startswith("Compression   "):
            code = d.split(": ", 1)[-1]
            if "jpeg" in code.lower():
                metadata.append({"code_type.lref": "401578"})
            elif "tiff" in code.lower():
                metadata.append({"code_type.lref": "131655"})
            elif "uncompressed" in code.lower():
                metadata.append({"code_type.lref": "392426"})
        elif d.startswith("Color Space Data "):
            metadata.append({"colour_space": d.split(": ", 1)[-1]})
        elif d.startswith("Description "):
            metadata.append({"description": d.split(": ", 1)[-1]})
            metadata.append({"description.name": "Digital file metadata"})
        elif d.startswith("Create Date "):
            try:
                val = d.split(": ", 1)[-1].split(" ", 1)[0].replace(":", "-")
                metadata.append({"production.date.start": val})
            except (KeyError, IndexError):
                pass
        if d.startswith("Creator   "):
            creator_data.append(d.split(": ", 1)[-1])
        elif d.startswith("Artist   "):
            creator_data.append(d.split(": ", 1)[-1])
        elif d.startswith("By-line   "):
            creator_data.append(d.split(": ", 1)[-1])
        if d.startswith("Rights   "):
            rights_data.append(d.split(": ", 1)[-1])
        elif d.startswith("Copyright Notice   "):
            rights_data.append(d.split(": ", 1)[-1])
        elif d.startswith("Copyright   "):
            rights_data.append(d.split(": ", 1)[-1])
        if d.startswith("Camera Model Name    "):
            metadata.append({"source_device": d.split(": ", 1)[-1]})

    if len(creator_data) > 0 and len(rights_data) > 0:
        creator_data.sort(key=len, reverse=True)
        rights_data.sort(key=len, reverse=True)
        metadata.append(
            {
                "production.notes": f"Photographer: {creator_data[0]}, Rights: {rights_data[0]}"
            }
        )
    elif len(creator_data) > 0:
        creator_data.sort(key=len, reverse=True)
        metadata.append({"production.notes": f"Photographer: {creator_data[0]}"})
    elif len(rights_data) > 0:
        rights_data.sort(key=len, reverse=True)
        metadata.append({"production.notes": f"Rights: {rights_data[0]}"})
    density = utils.get_metadata("Image", "Density/String", dpath)
    if density:
        metadata.append({"dimension.free": density})

    if len(metadata) > 0:
        return metadata, data
    return None, data


def write_exif_to_file(image: str, metadata: str) -> Optional[str]:
    """
    Create newline output to text file
    """

    meta_dump: str = os.path.join(MEDIAINFO_PATH, f"{image}_EXIF.txt")

    with open(meta_dump, "a+") as file:
        file.write(metadata)
        file.close()

    if os.path.isfile(meta_dump):
        return meta_dump
    return None


def create_new_image_record(
    record_json: str, session: requests.Session
) -> Optional[tuple[str, str]]:
    """
    Function for creation of new CID records
    both Analogue and Digital, returning priref/obj
    """
    print(record_json)
    record_xml = adlib.create_record_data(CID_API, "internalobject", "", record_json)
    print(record_xml)
    record = adlib.post(CID_API, record_xml, "internalobject", "insertrecord", session)
    if not record:
        LOGGER.warning(
            "Adlib POST failed to create CID item record for data:\n%s", record_xml
        )
        return None

    priref = adlib.retrieve_field_name(record, "priref")[0]
    obj = adlib.retrieve_field_name(record, "object_number")[0]
    return priref, obj


def write_payload(priref: str, payload_header: str, session: requests.Session) -> bool:
    """
    Payload formatting per mediainfo output
    """
    payload_head: str = f"<adlibXML><recordList><record priref='{priref}'>"
    payload_end: str = "</record></recordList></adlibXML>"
    payload: str = payload_head + payload_header + payload_end

    record = adlib.post(CID_API, payload, "internalobject", "updaterecord", session)
    if record is None:
        return False
    elif "error" in str(record):
        return False
    else:
        return True


def rename(filepath: str, ob_num: str) -> tuple[str, str]:
    """
    Receive original file path and rename filename
    based on object number, return new filepath, filename
    """
    new_filepath, new_filename = "", ""
    ipath, filename = os.path.split(filepath)
    ext = os.path.splitext(filename)[1]
    new_name = ob_num.replace("-", "_")
    new_filename = f"{new_name}_01of01{ext}"
    print(f"Renaming {filename} to {new_filename}")
    new_filepath = os.path.join(ipath, new_filename)

    try:
        os.rename(filepath, new_filepath)
    except OSError:
        LOGGER.warning("There was an error renaming %s to %s", filename, new_filename)

    return (new_filepath, new_filename)


def move(filepath: str, arg: str) -> bool:
    """
    Move existing filepaths to Autoingest
    """
    if os.path.exists(filepath) and "fail" in arg:
        pth: str = os.path.split(filepath)[0]
        failures: str = os.path.join(pth, "failures/")
        os.makedirs(failures, mode=0o777, exist_ok=True)
        print(f"move(): Moving {filepath} to {failures}")
        try:
            shutil.move(filepath, failures)
            return True
        except Exception as err:
            LOGGER.warning(
                "Error trying to move file %s to %s. Error %s", filepath, failures, err
            )
            return False
    elif os.path.exists(filepath) and "ingest" in arg:
        print(f"move(): Moving {filepath} to {AUTOINGEST}")
        try:
            shutil.move(filepath, AUTOINGEST)
            return True
        except Exception:
            LOGGER.warning("Error trying to move file %s to %s", filepath, AUTOINGEST)
            return False
    else:
        return False


if __name__ == "__main__":
    main()
