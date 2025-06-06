#!/usr/bin/env python3

"""
LEGACY VERSION TO PROCESS EXISTING MP4 FILES - NO TRANSCODE

Script to be launched from parallel, requires sys.argv arguments
to determine correct transcode paths (RNA or BFI).

1. Receives script path from sys.argv()
   Checks in CID to see if the file is accessible:
   - Yes, retrieves input date and acquisition source.
   - No, assume item record has restricted content and skip (go to stage 14).
2. Verifies MP4 passes mediaconch policy, gives warning if fails.
3. Passes through FFmpeg for blackdetect values
4. Uses duration to calculate how many seconds until 20% of total duration.
   Extract JPEG image from MP4 file checking blackdetected spaces
5. Uses 'gm' to generate full size(600x600ppi) and thumbnail(300x300ppi) from extracted JPEG.
6. Delete the first FFmpeg JPEG created from MP4 only.
7. Where JPEG or HLS assets (to follow) are created, write names to fields in CID media record.
8. Moves source file to completed folder for deletion.
9. Maintain log of all actions against file and dump in one lot to avoid log overlaps.

2024
Python 3.6+
"""

import datetime
import logging
# Public packages
import os
import re
import shutil
import subprocess
import sys
import time
from typing import Final, Optional, Union

import pytz
import tenacity

# Local packages
sys.path.append(os.environ["CODE"])
import adlib_v3 as adlib
import utils

# Global paths from environment vars
MP4_POLICY: Final = os.environ["MP4_POLICY"]
LOG_PATH: Final = os.environ["LOG_PATH"]
FLLPTH: Final = sys.argv[1].split("/")[:4]
LOG_PREFIX: Final = "_".join(FLLPTH)
LOG_FILE: Final = os.path.join(LOG_PATH, f"mp4_transcode_make_jpeg_legacy.log")
CID_API: Final = utils.get_current_api()
TRANSCODE: Final = os.environ["TRANSCODING"]
HOST: Final = os.uname()[1]

# Setup logging
LOGGER = logging.getLogger("mp4_transcode_make_jpeg_legacy")
HDLR = logging.FileHandler(LOG_FILE)
FORMATTER = logging.Formatter("%(asctime)s\t%(levelname)s\t%(message)s")
HDLR.setFormatter(FORMATTER)
LOGGER.addHandler(HDLR)
LOGGER.setLevel(logging.INFO)


def local_time() -> str:
    """
    Return strftime object formatted
    for London time (includes BST adjustment)
    """
    return datetime.datetime.now(pytz.timezone("Europe/London")).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def main():
    """
    Check sys.argv[1] populated
    Get ext, check filetype then process
    according to video, image or pass through
    audio and documents
    """
    if len(sys.argv) < 2:
        sys.exit("EXIT: Not enough arguments")

    fullpath: str = sys.argv[1]
    if not os.path.isfile(fullpath):
        sys.exit("EXIT: Supplied path is not a file")

    # Multiple instances of script so collection logs for one burst output
    if not utils.check_control("mp4_transcode"):
        LOGGER.info("Script run prevented by downtime_control.json. Script exiting.")
        sys.exit("Script run prevented by downtime_control.json. Script exiting.")
    if not utils.cid_check(CID_API):
        LOGGER.critical("* Cannot establish CID session, exiting script")
        sys.exit("* Cannot establish CID session, exiting script")
    log_build: list[str] = []

    filepath, file = os.path.split(fullpath)
    fname, ext = os.path.splitext(file)
    completed_pth = os.path.join(os.path.split(filepath)[0], "completed/", file)

    log_build.append(
        f"{local_time()}\tINFO\t================== START Transcode MP4 make JPEG {file} {HOST} =================="
    )
    print(f"File to be processed: {file}. Completed path: {completed_pth}")

    outpath, outpath2 = "", ""

    ext: str = ext.lstrip(".")
    duration, vs = get_duration(fullpath)
    print(file, fname, ext)
    # Check CID for Item record and extract transcode path
    object_number = utils.get_object_number(fname)
    if object_number == None or object_number is False:
        object_number = ""

    if object_number.startswith("CA_"):
        priref, source, groupings = check_item(object_number, "collectionsassets")
    else:
        priref, source, groupings = check_item(object_number, "items")
    # Check CID media record and extract input date for path
    (
        media_priref,
        input_date,
        largeimage,
        thumbnail,
        access,
        largeimage_old,
        thumbnail_old,
        access_old,
    ) = get_media_priref(file)
    if not media_priref:
        log_build.append(
            f"{local_time()}\tCRITICAL\tDigital media record priref missing: {file}"
        )
        log_build.append(
            f"{local_time()}\tINFO\t==================== END Transcode MP4 and make JPEG {file} ==================="
        )
        log_output(log_build)
        sys.exit("EXITING: Digital media record missing. See logs.")
    if not priref and not input_date:
        # Record inaccessible (possible access restrictions)
        log_build.append(
            f"{local_time()}\tWARNING\tProblems accessing CID to retrieve Item record data: {object_number}"
        )
        log_build.append(
            f"{local_time()}\tINFO\t==================== END Transcode MP4 and make JPEG {file} ==================="
        )
        log_output(log_build)
        sys.exit(f"EXITING: Unable to retrieve item details from CID: {object_number}")

    date_pth: str = input_date.replace("-", "")[:6]
    transcode_pth: str = os.path.join(TRANSCODE, "bfi", date_pth)

    # Check if transcode already completed
    if fname in access and thumbnail and largeimage:
        log_build.append(
            f"{local_time()}\tINFO\tMedia record already has Imagen Media UMIDs. Checking for transcodes"
        )
        if os.path.exists(os.path.join(transcode_pth, fname)):
            log_build.append(
                f"{local_time()}\tINFO\tTranscode file already exists. Moving {file} to completed folder"
            )
            try:
                shutil.move(fullpath, completed_pth)
            except Exception:
                log_build.append(
                    f"{local_time()}\tINFO\tMove to completed/ path has failed. Script exiting."
                )
            log_output(log_build)
            sys.exit(f"EXITING: File {file} has already been processed.")
        else:
            log_build.append(
                f"{local_time()}\tWARNING\tCID UMIDs exist but no transcoding. Allowing files to proceed."
            )
    elif fname in access_old and thumbnail_old and largeimage_old:
        log_build.append(
            f"{local_time()}\tINFO\tMedia record already has Imagen Media UMIDs. Checking for transcodes"
        )
        if os.path.exists(os.path.join(transcode_pth, fname)):
            log_build.append(
                f"{local_time()}\tINFO\tTranscode file already exists. Moving {file} to completed folder"
            )
            try:
                shutil.move(fullpath, completed_pth)
            except Exception:
                log_build.append(
                    f"{local_time()}\tINFO\tMove to completed/ path has failed. Script exiting."
                )
            log_output(log_build)
            sys.exit(f"EXITING: File {file} has already been processed.")
        else:
            log_build.append(
                f"{local_time()}\tWARNING\tCID UMIDs exist but no transcoding. Allowing files to proceed."
            )

    # Get file type, video or audio etc.
    ftype = utils.sort_ext(ext)
    if ftype != "video":
        log_build.append(f"{local_time()}\tINFO\tItem is not a video file. Skipping.")
        log_build.append(
            f"{local_time()}\tINFO\t==================== END Transcode MP4 and make JPEG {file} ==================="
        )
        log_output(log_build)
        sys.exit()

    log_build.append(f"{local_time()}\tINFO\tItem is video.")
    if not os.path.exists(transcode_pth):
        log_build.append(f"Creating new transcode path: {transcode_pth}")
        os.makedirs(transcode_pth, mode=0o777, exist_ok=True)

    # Mediaconch conformance check file
    policy_check: str = conformance_check(outpath)
    if "PASS!" in policy_check:
        log_build.append(
            f"{local_time()}\tINFO\tMediaconch pass! MP4 transcode complete. Beginning JPEG image generation."
        )
    else:
        log_build.append(
            f"{local_time()}\tINFO\tWARNING: MP4 failed policy check: {policy_check}"
        )

    # CID transcode paths
    outpath: str = os.path.join(transcode_pth, f"{fname}.mp4")
    outpath2: str = os.path.join(transcode_pth, fname)
    log_build.append(f"{local_time()}\tINFO\tMP4 destination will be: {outpath2}")

    # Build FFmpeg command based on dar/height
    ffmpeg_cmd: list[str] = create_transcode(fullpath)
    ffmpeg_call_neat: str = " ".join(ffmpeg_cmd)
    log_build.append(f"{local_time()}\tINFO\tFFmpeg call created:\n{ffmpeg_call_neat}")

    # Capture blackdetect info
    try:
        data = subprocess.run(
            ffmpeg_cmd,
            shell=False,
            check=True,
            universal_newlines=True,
            stderr=subprocess.PIPE,
        ).stderr
    except Exception as e:
        log_build.append(
            f"{local_time()}\tCRITICAL\tFFmpeg command failed: {ffmpeg_call_neat}"
        )
        log_build.append(
            f"{local_time()}\tINFO\t==================== END Transcode MP4 and make JPEG {file} ==================="
        )
        print(e)
        log_output(log_build)
        sys.exit("FFmpeg command failed. Script exiting.")

    time.sleep(5)

    # Start JPEG extraction
    jpeg_location: str = os.path.join(transcode_pth, f"{fname}.jpg")
    print(f"JPEG output to go here: {jpeg_location}")

    # Calculate seconds mark to grab screen
    seconds = adjust_seconds(duration, data)
    print(f"Seconds for JPEG cut: {seconds}")
    success = get_jpeg(seconds, outpath, jpeg_location)
    if not success:
        log_build.append(
            f"{local_time()}\tWARNING\tFailed to create JPEG from MP4 file"
        )
        log_build.append(
            f"{local_time()}\tINFO\t==================== END Transcode MP4 and make JPEG {file} ==================="
        )
        log_output(log_build)
        sys.exit("Exiting: JPEG not created from MP4 file")

    # Generate Full size 600x600, thumbnail 300x300
    full_jpeg = make_jpg(jpeg_location, "full", None, None)
    thumb_jpeg = make_jpg(jpeg_location, "thumb", None, None)
    if thumb_jpeg is None:
        thumb_jpeg = ""
    if full_jpeg is None:
        full_jpeg = ""
    log_build.append(
        f"{local_time()}\tINFO\tNew images created at {seconds} seconds into video:\n - {full_jpeg}\n - {thumb_jpeg}"
    )
    if os.path.isfile(full_jpeg) and os.path.isfile(thumb_jpeg):
        os.remove(jpeg_location)
    else:
        log_build.append(
            f"{local_time()}\tWARNING\tOne of the JPEG images hasn't created, please check outpath: {jpeg_location}"
        )

    # Clean up MP4 extension
    os.replace(outpath, outpath2)

    # Post MPEG/JPEG creation updates to Media record
    media_data: list[str] = []
    if full_jpeg:
        full_jpeg_file = os.path.splitext(full_jpeg)[0]
        print(full_jpeg, full_jpeg_file)
        os.replace(full_jpeg, full_jpeg_file)
        os.chmod(full_jpeg_file, 0o777)
        media_data.append(
            f"<access_rendition.largeimage>{os.path.split(full_jpeg_file)[1]}</access_rendition.largeimage>"
        )
    if thumb_jpeg:
        thumb_jpeg_file = os.path.splitext(thumb_jpeg)[0]
        os.replace(thumb_jpeg, thumb_jpeg_file)
        os.chmod(thumb_jpeg_file, 0o777)
        media_data.append(
            f"<access_rendition.thumbnail>{os.path.split(thumb_jpeg_file)[1]}</access_rendition.thumbnail>"
        )
    if outpath2:
        media_data.append(
            f"<access_rendition.mp4>{os.path.split(outpath2)[1]}</access_rendition.mp4>"
        )
        os.chmod(outpath2, 0o777)
    log_build.append(
        f"{local_time()}\tINFO\tWriting UMID data to CID Media record: {media_priref}"
    )

    success: Optional[bool] = cid_media_append(file, media_priref, media_data)
    if success:
        log_build.append(
            f"{local_time()}\tINFO\tJPEG/HLS filename data updated to CID media record"
        )
        log_build.append(
            f"{local_time()}\tINFO\tMoving preservation file to completed path: {completed_pth}"
        )
        shutil.move(fullpath, completed_pth)
    else:
        log_build.append(
            f"{local_time()}\tCRITICAL\tProblem writing UMID data to CID media record: {media_priref}"
        )
        log_build.append(
            f"{local_time()}\tWARNING\tLeaving files in transcode folder for repeat attempts to process"
        )
        # Any further clean up needed here?

    log_build.append(
        f"{local_time()}\tINFO\t==================== END Transcode MP4 and make JPEG {file} ===================="
    )
    log_output(log_build)


def log_output(log_build: list[str]) -> None:
    """
    Collect up log list and output to log in one block
    """
    for log in log_build:
        LOGGER.info(log)


def adjust_seconds(duration: int, data: str) -> int:
    """
    Adjust second durations within
    FFmpeg detected blackspace
    """
    blist: list[str] = retrieve_blackspaces(data)
    print(f"*** BLACK GAPS: {blist}")
    if not blist:
        return duration // 2

    secs: int = duration // 4
    clash: Optional[bool] = check_seconds(blist, secs)
    if not clash:
        return secs

    for num in range(2, 5):
        frame_secs: int = duration // num
        clash = check_seconds(blist, frame_secs)
        if not clash:
            return frame_secs

    if len(blist) > 2:
        first = blist[1].split(" - ")[1]
        second = blist[2].split(" - ")[0]
        frame_secs = int(first) + (int(second) - int(first)) // 2
        if int(first) < frame_secs < int(second):
            return frame_secs

    return duration // 2


def retrieve_blackspaces(data: str) -> list[str]:
    """
    Retrieve black detect log and check if
    second variable falls in blocks of blackdetected
    """
    data_list = data.splitlines()
    time_range = []
    for line in data_list:
        if "black_start" in line:
            split_line = line.split(":")
            split_start = split_line[1].split(".")[0]
            start = re.sub("[^0-9]", "", split_start)
            split_end = split_line[2].split(".")[0]
            end = re.sub("[^0-9]", "", split_end)
            # Round up to next second for cover
            end = str(int(end) + 1)
            time_range.append(f"{start} - {end}")
    return time_range


def check_seconds(blackspace: list[str], seconds: int) -> Optional[bool]:
    """
    Create range and check for second within
    """
    clash: list[int] = []
    for item in blackspace:
        start, end = item.split(" - ")
        st = int(start) - 1
        ed = int(end) + 1
        if seconds in range(st, ed):
            clash.append(seconds)

    if len(clash) > 0:
        return True


def get_jpeg(seconds: float, fullpath: str, outpath: str) -> bool:
    """
    Retrieve JPEG from MP4
    Seconds accepted as float
    """
    cmd: list[str] = [
        "ffmpeg",
        "-ss",
        str(seconds),
        "-i",
        fullpath,
        "-frames:v",
        "1",
        "-q:v",
        "2",
        outpath,
    ]

    command: str = " ".join(cmd)
    print("***********************")
    print(command)
    print("***********************")
    try:
        subprocess.call(cmd)
        return True
    except Exception as err:
        LOGGER.warning(
            "%s\tINFO\tget_jpeg(): failed to extract JPEG\n%s\n%s",
            local_time(),
            command,
            err,
        )
        return False


def check_item(ob_num: str, database: str) -> Optional[tuple[str, str, str]]:
    """
    Use requests to retrieve priref/RNA data for item object number
    """
    search: str = f"(object_number='{ob_num}')"
    record = adlib.retrieve_record(CID_API, database, search, "1")[1]
    if not record:
        record = adlib.retrieve_record(CID_API, "collect", search, "1")[1]
    if not record:
        return None

    priref = adlib.retrieve_field_name(record[0], "priref")[0]
    if not priref:
        priref = ""
    source = adlib.retrieve_field_name(record[0], "acquisition.source")[0]
    if not source:
        source = ""
    groupings = adlib.retrieve_field_name(record[0], "grouping")
    if not groupings:
        groupings = ""

    return priref, source, groupings


def get_media_priref(fname: str) -> Optional[tuple[str]]:
    """
    Retrieve priref from Digital record
    """
    search = f"(imagen.media.original_filename='{fname}')"
    record = adlib.retrieve_record(CID_API, "media", search, "1")[1]
    if not record:
        return None

    priref = adlib.retrieve_field_name(record[0], "priref")[0]
    if not priref:
        priref = ""
    input_date = adlib.retrieve_field_name(record[0], "input.date")[0]
    if not input_date:
        input_date = ""
    largeimage_umid = adlib.retrieve_field_name(
        record[0], "access_rendition.largeimage"
    )[0]
    if not largeimage_umid:
        largeimage_umid = ""
    thumbnail_umid = adlib.retrieve_field_name(record[0], "access_rendition.thumbnail")[
        0
    ]
    if not thumbnail_umid:
        thumbnail_umid = ""
    access_rendition = adlib.retrieve_field_name(record[0], "access_rendition.mp4")[0]
    if not access_rendition:
        access_rendition = ""

    return priref, input_date, largeimage_umid, thumbnail_umid, access_rendition


def get_dar(fullpath: str) -> str:
    """
    Retrieves metadata DAR info and returns as string
    """
    dar_setting = utils.get_metadata("Video", "DisplayAspectRatio/String", fullpath)
    if "4:3" in str(dar_setting):
        return "4:3"
    if "16:9" in str(dar_setting):
        return "16:9"
    if "15:11" in str(dar_setting):
        return "4:3"
    if "1.85:1" in str(dar_setting):
        return "1.85:1"
    if "2.2:1" in str(dar_setting):
        return "2.2:1"

    return str(dar_setting)


def get_par(fullpath: str) -> str:
    """
    Retrieves metadata PAR info and returns
    Checks if multiples from multi video tracks
    """

    par_full: str = utils.get_metadata("Video", "PixelAspectRatio", fullpath)

    if len(par_full) <= 5:
        return par_full
    else:
        return par_full[:5]


def get_height(fullpath: str) -> str:
    """
    Retrieves height information via mediainfo
    Using sampled height where original
    height and stored height differ (MXF samples)
    """

    sampled_height = utils.get_metadata("Video", "Sampled_Height", fullpath)
    reg_height = utils.get_metadata("Video", "Height", fullpath)
    try:
        int(sampled_height)
    except ValueError:
        sampled_height = 0

    if sampled_height == 0:
        height = str(reg_height)
    elif int(sampled_height) > int(reg_height):
        height = str(sampled_height)
    else:
        height = str(reg_height)

    if "480" == height:
        return "480"
    if "486" == height:
        return "486"
    if "576" == height:
        return "576"
    if "608" == height:
        return "608"
    if "720" == height:
        return "720"
    if "1080" == height or "1 080" == height:
        return "1080"
    else:
        height = height.split(" pixel", maxsplit=1)[0]
        return re.sub("[^0-9]", "", height)


def get_width(fullpath: str) -> str:
    """
    Retrieves height information using mediainfo
    """

    width = utils.get_metadata("Video", "Width/String", fullpath)

    if "720" == width:
        return "720"
    if "768" == width:
        return "768"
    if "1024" == width or "1 024" == width:
        return "1024"
    if "1280" == width or "1 280" == width:
        return "1280"
    if "1920" == width or "1 920" == width:
        return "1920"
    else:
        if width.isdigit():
            return str(width)
        else:
            width = width.split(" p", maxsplit=1)[0]
            return re.sub("[^0-9]", "", width)


def get_duration(fullpath: str) -> Optional[tuple[int, str]]:
    """
    Retrieves duration information via mediainfo
    where more than two returned, file longest of
    first two and return video stream info to main
    for update to ffmpeg map command
    """

    duration = utils.get_metadata("Video", "Duration", fullpath)
    if not duration:
        return (0, "")
    if "." in duration:
        duration = duration.split(".")
    print(f"Mediainfo seconds: {duration}")

    if isinstance(duration, str):
        second_duration = int(duration) // 1000
        return (second_duration, "0")
    elif len(duration) == 2:
        print("Just one duration returned")
        num = duration[0]
        second_duration = int(num) // 1000
        print(second_duration)
        return (second_duration, "0")
    elif len(duration) > 2:
        print("More than one duration returned")
        dur1 = f"{duration[0]}"
        dur2 = f"{duration[1][6:]}"
        print(dur1, dur2)
        if int(dur1) > int(dur2):
            second_duration = int(dur1) // 1000
            return (second_duration, "0")
        elif int(dur1) < int(dur2):
            second_duration = int(dur2) // 1000
            return (second_duration, "1")


def check_audio(fullpath: str) -> tuple[Optional[str], Optional[str]]:
    """
    Mediainfo command to retrieve channels, identify
    stereo or mono, returned as 2 or 1 respectively
    """

    cmd0: list[str] = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=index:stream_tags=language",
        "-of",
        "compact=p=0:nk=1",
        fullpath,
    ]

    cmd1: list[str] = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:1",
        "-show_entries",
        "stream=index:stream_tags=language",
        "-of",
        "compact=p=0:nk=1",
        fullpath,
    ]

    audio: str = utils.get_metadata("Audio", "Format", fullpath)
    if len(audio) == 0:
        return None, None

    try:
        lang0 = subprocess.check_output(cmd0)
        lang0_str = lang0.decode("utf-8")
    except Exception:
        lang0_str = ""
    try:
        lang1 = subprocess.check_output(cmd1)
        lang1_str = lang0.decode("utf-8")
    except Exception:
        lang1_str = ""

    print(f"**** LANGUAGES: Stream 0 {lang0_str} - Stream 1 {lang1_str}")

    if "nar" in str(lang0_str).lower():
        print("Narration stream 0 / English stream 1")
        return ("Audio", "1")
    elif "nar" in str(lang1_str).lower():
        print("Narration stream 1 / English stream 0")
        return ("Audio", "0")
    else:
        return ("Audio", None)


def create_transcode(fullpath: str) -> list[str]:
    """
    Builds FFmpeg command for blackdetect
    """

    ffmpeg_program_call: list[str] = ["ffmpeg"]

    input_video_file: list[str] = ["-i", fullpath]

    blackdetect: list[str] = ["-vf", "blackdetect=d=0.05:pix_th=0.1"]

    output: list[str] = ["-an", "-f", "null", "-", "2>&1"]

    return ffmpeg_program_call + input_video_file + blackdetect + output


def make_jpg(
    filepath: str, arg: str, transcode_pth: Optional[str], percent: Optional[str]
) -> Optional[str]:
    """
    Create GM JPEG using command based on argument
    These command work. For full size don't use resize.
    """

    start_reduce: list[str] = [
        "gm",
        "convert",
        "-density",
        "300x300",
        filepath,
        "-strip",
    ]

    start: list[str] = ["gm", "convert", "-density", "600x600", filepath, "-strip"]

    thumb: list[str] = [
        "-resize",
        "x180",
    ]

    oversize: list[str] = [
        "-resize",
        f"{percent}%x{percent}%",
    ]

    if not transcode_pth:
        out = os.path.splitext(filepath)[0]
    else:
        fname: str = os.path.split(filepath)[1]
        file: str = os.path.splitext(fname)[0]
        out = os.path.join(transcode_pth, file)

    if "thumb" in arg:
        outfile = f"{out}_thumbnail.jpg"
        cmd = start_reduce + thumb + [f"{outfile}"]
    elif "oversize" in arg:
        outfile = f"{out}_largeimage.jpg"
        cmd = start + oversize + [f"{outfile}"]
    else:
        outfile = f"{out}_largeimage.jpg"
        cmd = start + [f"{outfile}"]

    try:
        subprocess.call(cmd)
    except Exception as err:
        LOGGER.error(
            "%s\tERROR\tJPEG creation failed for filepath: %s\n%s",
            local_time(),
            filepath,
            err,
        )

    if os.path.exists(outfile):
        return outfile


def conformance_check(file: str) -> str:
    """
    Checks file against MP4 mediaconch policy
    Looks for essential items to ensure that
    the transcode was successful
    """

    mediaconch_cmd: list[str] = ["mediaconch", "--force", "-p", MP4_POLICY, file]

    try:
        success = str(subprocess.check_output(mediaconch_cmd))
    except Exception as err:
        success = ""
        LOGGER.warning(
            "%s\tWARNING\tMediaconch policy retrieval failure for %s\n%s",
            local_time(),
            file,
            err,
        )

    if "pass!" in str(success):
        return "PASS!"
    elif success.startswith("fail!"):
        return f"FAIL! This policy has failed {success}"
    else:
        return "FAIL!"


@tenacity.retry(stop=tenacity.stop_after_attempt(10))
def cid_media_append(fname: str, priref: str, data: list[str]) -> Optional[bool]:
    """
    Receive data and priref and append to CID media record
    """
    payload_head: str = f"<adlibXML><recordList><record priref='{priref}'>"
    payload_mid: str = "".join(data)
    payload_end: str = f"</record></recordList></adlibXML>"
    payload: str = payload_head + payload_mid + payload_end

    rec = adlib.post(CID_API, payload, "media", "updaterecord")
    if not rec:
        return False

    data_priref = get_media_priref(fname)
    print("**************************************************************")
    print(data)
    print("**************************************************************")

    data_priref = get_media_priref(fname)
    if data_priref is None:
        data_priref = tuple("")
        return False
    file = fname.split(".")[0]
    if file == data_priref[4]:
        LOGGER.info(
            "cid_media_append(): Write of access_rendition data confirmed successful for %s - Priref %s",
            fname,
            priref,
        )
        return True


if __name__ == "__main__":
    main()
