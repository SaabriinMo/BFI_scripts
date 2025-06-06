#!/usr/bin/env python3

"""
USES SYS.ARGV[] to receive path to item for TAR.
Complete TAR wrapping using Python3 tarfile
on folder or file supplied in tar watch folder.
Compare TAR contents to original using MD5 hash.

Steps:
1. Assess if item supplied is folder or file
2. Check filename and retrieve priref/file_type
   from CID item record
3. Initiate TAR wrapping with zero compression
4. Generate MD5 dict for original folder
5. Generate MD5 dict for internals of TAR
6. Compare to ensure identical:
   Yes. Output MD5 to manifest and add into TAR file
        Move original folder to 'delete' folder
        Move completed closed() TAR to autoingest.
        Update details to local log.
   No. Delete faulty TAR.
       Output warning to Local log and leave file
       for retry at later date.
7. Write 'Python tarfile' note to CID item record

2022
"""

import datetime
import hashlib
import json
import logging
import os
import shutil
import sys
import tarfile
from typing import Final, Optional

sys.path.append(os.environ["CODE"])
import adlib_v3 as adlib
import utils

# Global paths
AUTO_TAR: Final = os.environ["AUTOMATION_WAV"]
AUTOINGEST: Final = os.path.join(os.environ["QNAP_08"], os.environ["AUTOINGEST_STORE"])
LOG: Final = os.path.join(os.environ["LOG_PATH"], "tar_wrapping_check_audio_ops.log")
CID_API: Final = utils.get_current_api()

# Logging config
LOGGER = logging.getLogger("tar_wrapping_check_audio_ops")
hdlr = logging.FileHandler(LOG)
formatter = logging.Formatter("%(asctime)s\t%(levelname)s\t%(message)s")
hdlr.setFormatter(formatter)
LOGGER.addHandler(hdlr)
LOGGER.setLevel(logging.INFO)


def get_cid_data(fname: str) -> Optional[tuple[str, str, str]]:
    """
    Use requests to retrieve priref for associated item object number
    """

    ob_num_split = fname.split("_")
    if len(ob_num_split) == 3:
        ob_num = "-".join(ob_num_split[0:2])
    elif len(ob_num_split) == 4:
        ob_num = "-".join(ob_num_split[0:3])
    else:
        LOGGER.warning(
            "Incorrect filename formatting, cannot retrieve Priref for: %s.", fname
        )
        return None

    search = f"object_number='{ob_num}'"
    results = adlib.retrieve_record(
        CID_API, "items", search, "1", ["priref", "file_type", "input.notes"]
    )[1]
    if not results:
        return None
    try:
        priref = adlib.retrieve_field_name(results[0], "priref")[0]
    except (IndexError, KeyError):
        priref = ""
    try:

        file_type = adlib.retrieve_field_name(results[0], "file_type")[0]
    except (IndexError, KeyError):
        file_type = ""
    try:
        input_note = adlib.retrieve_field_name(results[0], "input.notes")[0]
    except (IndexError, KeyError):
        input_note = ""
    return priref, file_type, input_note


def tar_file(fpath: str) -> Optional[str]:
    """
    Make tar path from supplied filepath
    Use tarfile to create TAR
    """
    split_path = os.path.split(fpath)
    tfile = f"{split_path[1]}.tar"
    tar_path = os.path.join(split_path[0], tfile)
    if os.path.exists(tar_path):
        LOGGER.warning("tar_file(): FILE ALREADY EXISTS %s", tar_path)
        return None

    try:
        tarring = tarfile.open(tar_path, "w:")
        tarring.add(fpath, arcname=f"{split_path[1]}")
        tarring.close()
        return tar_path

    except Exception as exc:
        LOGGER.warning("tar_file(): ERROR WITH TAR WRAP %s", exc)
        tarring.close()
        return None


def get_tar_checksums(tar_path: str, folder: str) -> dict[str, str]:
    """
    Open tar file and read/generate MD5 sums
    and return dct {filename: hex}
    """
    data = {}
    tar = tarfile.open(tar_path, "r|")

    for item in tar:
        item_name = item.name
        if item.isdir():
            continue

        fname = os.path.basename(item_name)
        print(item_name, fname, item)

        try:
            f = tar.extractfile(item)
        except Exception as exc:
            LOGGER.warning(
                "get_tar_checksums(): Unable to extract from tar file\n%s", exc
            )
            continue

        hash_md5 = hashlib.md5()
        for chunk in iter(lambda: f.read(65536), b""):
            hash_md5.update(chunk)

        if not folder:
            file = os.path.basename(fname)
            data[file] = hash_md5.hexdigest()
        else:
            data[fname] = hash_md5.hexdigest()

    return data


def get_checksum(fpath: str) -> dict[str, str]:
    """
    Using file path, generate file checksum
    return as list with filename
    """
    data = {}
    file = os.path.split(fpath)[1]
    hash_md5 = hashlib.md5()
    with open(fpath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hash_md5.update(chunk)
        data[file] = hash_md5.hexdigest()
        f.close()
    return data


def make_manifest(tar_path: str, md5_dct: dict[str, str]) -> str:
    """
    Output md5 to JSON file format and add to TAR file
    """
    md5_path = f"{tar_path}_manifest.md5"

    try:
        with open(md5_path, "w+") as json_file:
            json_file.write(json.dumps(md5_dct, indent=4))
            json_file.close()
    except Exception as exc:
        LOGGER.warning("make_manifest(): FAILED to create JSON %s", exc)

    if os.path.exists(md5_path):
        return md5_path


def main():
    """
    Receive SYS.ARGV and check path exists or is file/folder
    Generate checksums for all folder contents/single file
    TAR Wrap, then make checksum for inside of TAR contents
    Compare checksum manifests, if match add into TAR and close.
    Delete original file, move TAR to autoingest path.
    """

    if len(sys.argv) != 2:
        LOGGER.warning("SCRIPT EXIT: Error with shell script input:\n %s", sys.argv)
        sys.exit()

    fullpath = sys.argv[1]
    print(fullpath)

    if not os.path.exists(fullpath):
        sys.exit("Supplied path does not exists. Please try again.")

    log = []
    log.append(f"\n==== New path for TAR wrap: {fullpath} ====")
    LOGGER.info("==== TAR Wrapping Check script start ===============================")
    LOGGER.info("Path received for TAR wrap using Python3 tarfile: %s", fullpath)
    split_path = os.path.split(fullpath)
    tar_source = split_path[1]
    if not tar_source.startswith(
        ("N_", "C_", "PD_", "SPD_", "PBS_", "PBM_", "PBL_", "SCR_", "CA_")
    ):
        LOGGER.warning("Exiting: Filename is not formatted correctly: %s", tar_source)
        log.append(
            f"Filename is not formatted correctly {tar_source}.\n \
                   Please ensure file is named as CID item record for ingest to DPI (eg, N_123456_01of01)"
        )
        log.append(f"==== Log actions complete: {fullpath} ====")
        for item in log:
            local_logs(AUTO_TAR, item)
        sys.exit()

    part_whole = tar_source.split("_")[-1]
    if "of" not in str(part_whole):
        LOGGER.warning("Exiting: Filename is not formatted correctly: %s", tar_source)
        log.append(
            f"Filename is not formatted correctly {tar_source}.\n \
                   Please ensure file is named with part whole data (eg, N_123456_01of01)"
        )
        log.append(f"==== Log actions complete: {fullpath} ====")
        for item in log:
            local_logs(AUTO_TAR, item)
        sys.exit()

    # Attempt to retrieve CID item record
    data = get_cid_data(tar_source)
    if not data[0]:
        log.append("Unable to retrieve priref or file_type for this record. Exiting.")
        log.append(f"==== Log actions complete: {fullpath} ====")
        for item in log:
            local_logs(AUTO_TAR, item)
        sys.exit()

    priref = data[0]
    file_type = data[1]
    input_note = data[2]
    if file_type.lower() != "wav" or file_type.lower() != "tar":
        log.append(
            f"WARNING: Please review this file's file_type in CID Item record {priref} as file type is not 'WAV'"
        )
    if (
        file_type.lower() == "tar"
        and "Created by automation to aid ingest of legacy projects and workflows."
        not in input_note
    ):
        log.append(
            f"WARNING: Please review this file's file_type in CID Item record {priref} as file type is 'TAR' but not from automation workflow"
        )

    # Make paths for moving later
    failures_path = os.path.join(AUTO_TAR, "failures/")
    delete_path = os.path.join(AUTO_TAR, "to_delete/")
    oversize_path = os.path.join(AUTO_TAR, "oversize/")
    checksum_path = os.path.join(AUTO_TAR, "checksum_manifests/")

    # Calculate checksum manifest for supplied fullpath
    local_md5 = {}
    directory = False
    if os.path.isdir(fullpath):
        directory = True

    if directory:
        files = [
            x for x in os.listdir(fullpath) if os.path.isfile(os.path.join(fullpath, x))
        ]
        for root, _, files in os.walk(fullpath):
            LOGGER.info("Path is directory.")
            log.append("Path is directory.")
            for file in files:
                dct = get_checksum(os.path.join(root, file))
                local_md5.update(dct)

    else:
        local_md5 = get_checksum(fullpath)
        log.append("Path is not a directory and will be wrapped alone")

    LOGGER.info("Checksums for local files:")
    log.append("Checksums for local files:")
    for key, val in local_md5.items():
        data = f"{val} -- {key}"
        LOGGER.info("\t%s", data)
        log.append(f"\t{data}")

    # Tar folder
    log.append("Beginning TAR wrap now...")
    tar_path = tar_file(fullpath)
    if not tar_path:
        log.append("TAR WRAP FAILED. SCRIPT EXITING!")
        LOGGER.warning("TAR wrap failed for file: %s", fullpath)
        for item in log:
            local_logs(AUTO_TAR, item)
        sys.exit(f"EXIT: TAR wrap failed for {fullpath}")

    # Calculate checksum manifest for TAR folder
    if directory:
        tar_content_md5 = get_tar_checksums(tar_path, tar_source)
    else:
        tar_content_md5 = get_tar_checksums(tar_path, "")

    log.append("Checksums from TAR wrapped contents:")
    LOGGER.info("Checksums for TAR wrapped contents:")
    for key, val in tar_content_md5.items():
        data = f"{val} -- {key}"
        LOGGER.info("\t%s", data)
        log.append(f"\t{data}")

    # Compare manifests
    if local_md5 == tar_content_md5:
        log.append(
            "MD5 Manifests match, adding manifest to TAR file and moving to autoingest."
        )
        LOGGER.info("MD5 manifests match.")
        md5_manifest = make_manifest(tar_path, tar_content_md5)
        if not md5_manifest:
            LOGGER.warning("Failed to write TAR checksum manifest to JSON file.")
            shutil.move(tar_path, os.path.join(failures_path, f"{tar_source}.tar"))
            for item in log:
                local_logs(AUTO_TAR, item)
            sys.exit("Script exit: TAR file MD5 Manifest failed to create")

        LOGGER.info("TAR checksum manifest created. Adding to TAR file %s", tar_path)
        try:
            arc_path = os.path.split(md5_manifest)
            tar = tarfile.open(tar_path, "a:")
            tar.add(md5_manifest, arcname=f"{arc_path[1]}")
            tar.close()
        except Exception as exc:
            LOGGER.warning(
                "Unable to add MD5 manifest to TAR file. Moving TAR file to errors folder.\n%s",
                exc,
            )
            shutil.move(tar_path, os.path.join(failures_path, f"{tar_source}.tar"))
            # Write all log items in block
            for item in log:
                local_logs(AUTO_TAR, item)
            sys.exit("Failed to add MD5 manifest To TAR file. Script exiting")

        LOGGER.info(
            "TAR MD5 manifest added to TAR file. Getting wholefile TAR checksum for logs"
        )

        # Get complete TAR wholefile Checksums for logs
        tar_md5 = get_tar_checksums(tar_path, "")
        log.append(f"TAR checksum: {tar_md5} for TAR file: {tar_path}")
        LOGGER.info("TAR checksum: %s", tar_md5)
        # Get complete size of file following TAR wrap
        file_stats = os.stat(tar_path)
        log.append(f"File size is {file_stats.st_size} bytes")
        LOGGER.info("File size is %s bytes.", file_stats.st_size)
        if file_stats.st_size > 1099511627770:
            log.append(
                "FILE IS TOO LARGE FOR INGEST TO BLACK PEARL. Moving to oversized folder path"
            )
            LOGGER.warning(
                "MOVING TO OVERSIZE PATH: Filesize too large for ingest to DPI"
            )
            shutil.move(tar_path, os.path.join(oversize_path, f"{tar_source}.tar"))

        log.append(
            "Moving TAR file to Autoingest, and moving source file to deletions path."
        )
        shutil.move(tar_path, AUTOINGEST)
        LOGGER.info("Moving original file to deletions folder: %s", fullpath)
        deletion_path = os.path.join(delete_path, tar_source)
        print(deletion_path)
        shutil.move(fullpath, deletion_path)
        # Add deletion here
        try:
            os.chmod(deletion_path, 0o777)
            os.rmdir(deletion_path)
            LOGGER.info("File deleted: %s", deletion_path)
        except Exception as err:
            LOGGER.warning(
                "WARNING: File could not be deleted %s\n%s", deletion_path, err
            )
        LOGGER.info("Moving MD5 manifest to checksum_manifest folder")
        shutil.move(md5_manifest, checksum_path)

        # Write note to CID Item record that file has been wrapped using Python tarfile module.
        success = write_to_cid(priref, tar_source)
        if not success:
            LOGGER.warning(
                "CID item record was not updated with Python tarfile note. Please update manually:"
            )
            LOGGER.warning(
                "For preservation to DPI the item %s was wrapped using Python tarfile module, and the TAR includes checksum manifests of all contents.",
                tar_source,
            )

    else:
        LOGGER.warning(
            "Manifests do not match.\nLocal:\n%s\nTAR:\n%s", local_md5, tar_content_md5
        )
        LOGGER.warning("Moving TAR file to failures, leaving file/folder for retry.")
        log.append(
            "MD5 manifests do not match. Moving TAR file to failures folder for retry"
        )
        shutil.move(tar_path, os.path.join(failures_path, f"{tar_source}.tar"))

    log.append(f"==== Log actions complete: {fullpath} ====")
    # Write all log items in block
    for item in log:
        local_logs(AUTO_TAR, item)

    LOGGER.info("==== TAR Wrapping Check script END =================================")


def local_logs(fullpath: str, data: str) -> None:
    """
    Output local log data for team
    to monitor TAR wrap process
    """
    local_log = os.path.join(fullpath, "tar_wrapping_checksum.log")
    timestamp = str(datetime.datetime.now())

    if not os.path.isfile(local_log):
        with open(local_log, "x") as log:
            log.close()

    with open(local_log, "a") as log:
        log.write(f"{timestamp[0:19]} - {data}\n")
        log.close()


def write_to_cid(priref: str, fname: str) -> bool:
    """
    Make payload and write to CID
    """
    name = "datadigipres"
    method = "TAR wrapping method:"
    text = f"For preservation to DPI the item {fname} was wrapped using Python tarfile module, and the TAR includes checksum manifests of all contents."
    date = str(datetime.datetime.now())[:10]
    time = str(datetime.datetime.now())[11:19]
    notes = "Automated TAR wrapping script."
    payload_head = f"<adlibXML><recordList><record priref='{priref}'>"
    payload_addition = (
        f"<utb.fieldname>{method}</utb.fieldname><utb.content>{text}</utb.content>"
    )
    payload_edit = f"<edit.name>{name}</edit.name><edit.date>{date}</edit.date><edit.time>{time}</edit.time><edit.notes>{notes}</edit.notes>"
    payload_end = "</record></recordList></adlibXML>"
    payload = payload_head + payload_addition + payload_edit + payload_end

    record = adlib.post(CID_API, payload, "items", "updaterecord")
    if record is None:
        LOGGER.warning(
            "write_to_cid(): Error returned for adlib.post to %s\n%s", priref, payload
        )
        return False
    elif "priref" in str(record):
        LOGGER.info(
            "write_to_cid(): Payload successfully written to CID item record %s", priref
        )
        return True


if __name__ == "__main__":
    main()
