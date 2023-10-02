import os
import subprocess
import re
import torf
import argparse
import cli_ui
import urllib.request
import requests
import glob
import csv
from humanfriendly import format_size, parse_size
from qbittorrentapi import Client
from themoviedb import TMDb
from wand.image import Image
from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader
from pymediainfo import MediaInfo



config = {
    'announce': 'http://tracker.zelka.org/announce.php?passkey=<PASS_KEY>',
    'qbit_host': 'https://hostname:port',
    'qbit_user': '',
    'qbit_pass': '',
    'tmdb_api_key': '<TMDB_API_KEY>',
    'output_base_dir': '<PATH FOR TEMPORARY DATA>',
    'bitbucket_url': 'http://img.zamunda.se:8080/bitbucket-upload.php',
    'cookie': '<SITE COOKIE VALUE>'
}

def extract_file_name(path):
    return os.path.splitext(os.path.basename(path))[0]

def parse_args():
    parser = argparse.ArgumentParser(
      prog = 'ac-uploader',
      description = 'Inject .torrent files into qbit without checking')

    parser.add_argument('-tmdb', '--tmdb', required = True, help = 'TMDb movie ID')
    parser.add_argument('PATH', help='Path to .mkv file')

    args = parser.parse_args()
    return args.PATH, args.tmdb

def create_output_dir(path):
    d = os.path.join(config['output_base_dir'], extract_file_name(path))
    if not os.path.exists(d):
        os.makedirs(d)
    cli_ui.info(cli_ui.green, "Output dir:", cli_ui.reset, d)
    return d

def calc_piece_size(path):
    fileSize = os.stat(path).st_size
    if fileSize <= parse_size('100 MiB'):
        return parse_size('128 KiB')
    elif fileSize <= parse_size('700 MiB'):
        return parse_size('256 KiB')
    elif fileSize <= parse_size('2 GiB'):
        return parse_size('1 MiB')
    elif fileSize <= parse_size('5 MiB'):
        return parse_size('2 MiB')
    elif fileSize <= parse_size('50 GiB'):
        return parse_size('4 MiB')
    elif fileSize <= parse_size('100 GiB'):
        return parse_size('8 MiB')
    elif fileSize > parse_size('100 GiB'):
        return parse_size('16 MiB')
    else:
        return parse_size('256 KiB')

def torf_cb(torrent, filepath, pieces_done, pieces_total):
    cli_ui.info_progress(f"Hashing: [{pieces_done}/{pieces_total}] ", pieces_done, pieces_total)


def create_torrent(outputDir, path):
    torrent = torf.Torrent(
        path=path,
        # name=None,
        # exclude_globs=(),
        # exclude_regexs=(),
        # include_globs=(),
        # include_regexs=(),
        trackers=[config['announce']],
        # webseeds=None,
        # httpseeds=None,
        # private=None,
        # comment=None,
        # source=None,
        # creation_date=None,
        created_by='ac-uploader',
        piece_size=calc_piece_size(path),
        # piece_size_min=None,
        # piece_size_max=None,
        # randomize_infohash=False
    )

    torrentFile = os.path.join(outputDir, extract_file_name(path) + ".torrent")

    torrent.generate(callback=torf_cb, interval=1)
    torrent.write(torrentFile, overwrite=True)
    torrent.verify_filesize(path)

    cli_ui.info(cli_ui.green, "Torrent created:", cli_ui.reset, os.path.basename(torrentFile))

    return torrentFile

def inject_torrent_qbit(torrentFile):
    client = Client(host=config['qbit_host'], username=config['qbit_user'], password=config['qbit_pass'])

    # Custom qbit category selection based on torrent path
    if 'own-remux-bd' in target:
        category = 'own-remux-bd'
    elif 'own-remux-hybrid' in target:
        category = 'own-remux-hybrid'
    else:
        print('Cannot extrapolate qbit category from path')
        exit(1)

    qbit_result = client.torrents_add(
        urls=None,
        torrent_files=torrentFile,
        # save_path=None,
        # cookie=None,
        category=category,
        is_skip_checking=True,
        is_paused=False,
        # is_root_folder=None,
        # rename=None,
        # upload_limit=None,
        # download_limit=None,
        use_auto_torrent_management=True,
        # is_sequential_download=None,
        # is_first_last_piece_priority=None,
        tags='own-upload',
        content_layout='Original',
        # ratio_limit=None,
        # seeding_time_limit=None,
        # download_path=None,
        # use_download_path=None,
        # stop_condition=None,
        # **kwargs
    )

    cli_ui.info(cli_ui.green, "Injecting torrent to client:", cli_ui.reset, qbit_result)

def csv_mapping(csvFile):
    langMap = {}
    with open(csvFile, "r") as f:
        reader = csv.reader(f, delimiter = ',')
        for r in reader:
            langMap[r[0]] = r[1]
    return langMap

def extract_languages(path, track_type):
    langMap = csv_mapping('./en-bg-lang-mapping.csv')
    info = MediaInfo.parse(path)
    trackLangs = map(lambda x: x.other_language[0], filter(lambda x: x.track_type == track_type, info.tracks))
    translated = list(set(map(lambda x: langMap[x], trackLangs)))
    if 'Английски' in translated:
        translated.remove('Английски')
        translated.insert(0, 'Английски')
    return ', '.join(translated)

def tmdb_poster(outputDir, tmdb_id):
    db = TMDb(key = config['tmdb_api_key'])
    movie = db.movie(tmdb_id)
    movieDetails = movie.details()

    # Download and resize poster image
    posterUrl = movieDetails.poster_url()
    posterFile = os.path.join(outputDir, "poster.jpg")
    urllib.request.urlretrieve(posterUrl, posterFile)

    posterResizedFile = os.path.join(outputDir, "poster-600.jpg")
    with Image(filename = posterFile) as img:
        img.transform(resize = '600x')
        img.save(filename = posterResizedFile)

    cli_ui.info(cli_ui.green, "Poster ready:", cli_ui.reset, os.path.basename(posterResizedFile))

def tmdb_metadata(tmdb_id):
    db = TMDb(key = config['tmdb_api_key'])
    movie = db.movie(tmdb_id)
    movieDetails = movie.details()

    countryIso = movieDetails.production_countries[0].iso_3166_1
    countryMap = csv_mapping('./country-iso-3166-1.csv')

    return {
        'duration': movieDetails.runtime,
        'year': movieDetails.year,
        'country': countryMap[countryIso],
        'imdb_url': movieDetails.imdb_url
    }

def extract_mediainfo(outputDir, path):
    result = subprocess.run(["mediainfo", path], capture_output=True, text=True)
    # Remove local path prefix from mediainfo output
    cleanResult = re.sub("/mnt/vol./t3/own-remux.*/", "", result.stdout)

    nfoFile = os.path.join(outputDir, extract_file_name(path) + ".nfo")
    with open(nfoFile, 'w') as f:
        f.write(cleanResult)

    cli_ui.info(cli_ui.green, "NFO file ready:", cli_ui.reset, os.path.basename(nfoFile))

def generate_screenshots(outputDir, path):
    subprocess.run(['./ssnap', path, '4', outputDir], stdout = subprocess.DEVNULL)
    cli_ui.info(cli_ui.green, "Screenshots generated")

def upload_images(outputDir, path):
    screenshots = glob.glob(f"{outputDir}/screenshot-*.jpg")
    if len(screenshots) != 4:
        print("The number of screenshots does not match")
        exit(1)

    files = {
        'file1': open(os.path.join(outputDir, 'poster-600.jpg'), 'rb'),
        'file2': open(screenshots[0], 'rb'),
        'file3': open(screenshots[1], 'rb'),
        'file4': open(screenshots[2], 'rb'),
        'file5': open(screenshots[3], 'rb'),
    }
    headers = {
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.8',
        'Cache-Control': 'max-age=0',
        'Connection': 'keep-alive',
        'Cookie': config['cookie'],
        'Origin': 'http://img.zamunda.se:8080',
        'Referer': 'http://img.zamunda.se:8080/bitbucket-upload.php?stafff=1',
        'Sec-GPC': '1',
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
    }
    response = requests.post(config['bitbucket_url'], files=files, headers=headers)

    # Parse response and extract links
    soup = BeautifulSoup(response.text, features="html.parser")
    uploads = list( map(lambda a: a["href"], filter(lambda a: not a["href"].startswith("/") and not a["href"].startswith("javascript"), soup("a"))))

    return uploads

def user_input():
    userInputDict = {}

    userInputDict['director'] = input('Director?\n')
    userInputDict['writer'] = input('Writer?\n')
    userInputDict['producer'] = input('Producer?\n')
    userInputDict['cast'] = input('Cast?\n')

    print('Description (Ctrl-D to finish):')
    description = []
    while True:
        try:
            user_in = input()
            if user_in == '\n':
                description.append('\n')
            description.append(user_in)
        except EOFError:
            break
    userInputDict['description'] = '\n'.join(description).strip()

    return userInputDict

def generate_description(outputDir, path, tmdb_id):
    # Gather data
    uploads = upload_images(outputDir, path)
    audioLanguages = extract_languages(target, 'Audio')
    subtitleLanguages = extract_languages(target, 'Text')
    movieMeta = tmdb_metadata(tmdb_id)
    userInput = user_input()

    # Render description template
    environment = Environment(loader=FileSystemLoader("./"))
    template = environment.get_template("description-template")
    content = template.render(
        poster = uploads[0],
        shot1 = uploads[1],
        shot2 = uploads[2],
        shot3 = uploads[3],
        shot4 = uploads[4],
        audio_languages = audioLanguages,
        subtitle_languages = subtitleLanguages,
        duration = movieMeta['duration'],
        year = movieMeta['year'],
        country = movieMeta['country'],
        imdb_url = movieMeta['imdb_url'],
        director = userInput['director'],
        writer = userInput['writer'],
        producer = userInput['producer'],
        cast = userInput['cast'],
        description = userInput['description']
    )
    descriptionFile = os.path.join(outputDir, 'description.txt')
    with open(descriptionFile, mode="w", encoding="utf-8") as message:
        message.write(content)
        cli_ui.info(cli_ui.green, "Description file ready:", cli_ui.reset, os.path.basename(descriptionFile))


target, tmdb_id = parse_args()
outputDir = create_output_dir(target)
tmdb_poster(outputDir, tmdb_id)
extract_mediainfo(outputDir, target)
generate_screenshots(outputDir, target)
generate_description(outputDir, target, tmdb_id)
torrentFile = create_torrent(outputDir, target)
inject_torrent_qbit(torrentFile)
