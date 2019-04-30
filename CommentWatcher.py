import praw
from prawcore import PrawcoreException

import config
import logging
import re
import shelve
from multiprocessing import Queue, Process
from TaskExecution import Task
import time
import spotipy


class AddTrack(Task):
    def __init__(self, playlist_id, artist, song_name):
        self.playlist_id = playlist_id
        self.artist = artist
        self.song_name = song_name

    def do_spotify_task(self, spotify: spotipy.Spotify, logger: logging.Logger):
        logger.debug(f"Searching for query \"artist:{self.artist} track:{self.song_name}\"")
        items = spotify.search(q=f"artist:{self.artist} track:{self.song_name}", type=["tracks"])['tracks']['items']
        if len(items) <= 0:
            logger.warning(f"Could not find song {self.song_name} with artist {self.artist}")
            return
        uri = items[0]['uri']
        spotify.user_playlist_add_tracks(config.USERNAME, playlist_id=self.playlist_id, tracks=[uri])
        logger.debug("Added song to playlist")

    def do_reddit_task(self, reddit: praw.Reddit, logger: logging.Logger, submission):
        pass


class CommentWatcher(Process):
    def __init__(self, task_queue: Queue, monitor_submissions):
        super(CommentWatcher, self).__init__()
        self.task_queue = task_queue
        self.monitor_submission = monitor_submissions
        self.comment_monitor = shelve.open("votes.db", writeback=True)
        self.matcher = re.compile("!add (.*) by (.*)")

        self.logger = logging.Logger(__name__)
        self.logger.setLevel(logging.DEBUG)
        file_handler = logging.FileHandler(__name__ + ".log")
        file_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

        try:
            self.reddit = praw.Reddit(client_id=config.REDDIT_ID, client_secret=config.REDDIT_SECRET,
                                      username=config.USERNAME,
                                      password=config.REDDIT_PASSWORD, user_agent="LetsMakeAPlaylist")
            self.subreddit = self.reddit.subreddit(config.SUBREDDIT)
        except Exception as e:
            self.logger.error("Error making the reddit object: " + str(e))

    def monitor_comments(self) -> None:
        for comment in self.subreddit.stream.comments(skip_existing=True):
            if comment.body.startswith("!add"):
                if self.matcher.match(
                        comment.body) and comment.submission.id in self.monitor_submission and comment.parent_id == comment.link_id:
                    if self.monitor_submission[comment.submission.id][0] <= 1:
                        while len(self.monitor_submission[comment.submission.id]) < 2:
                            print("Waiting")
                            time.sleep(2)
                        add_comment = self.reddit.comment(id=comment.id.split("_")[-1])
                        self.logger.debug("Adding " + add_comment.body + " to spotify playlist " +
                                          self.monitor_submission[comment.submission.id][1])
                        split = add_comment.body.split("by")
                        artist = split[-1].strip()
                        song = split[0].split(" ")[-1]
                        self.task_queue.put(
                            [AddTrack(self.monitor_submission[comment.submission.id][1], artist, song), add_comment])
                    else:
                        self.logger.debug(f"Added new submission with id {comment.id}")
                        self.comment_monitor[comment.id] = set()
                        self.comment_monitor.sync()
                else:
                    comment.reply("To add a song suggestion please make sure you comment on the post itself and "
                                  "follows the following format:  \n "
                                  "!add <song name> by <artist>")
            elif comment.body.lower() == "!vote" and comment.parent_id.split("_")[-1] in self.comment_monitor:
                self.logger.debug("Someone voted")
                vote_set = self.comment_monitor[comment.parent_id.split("_")[-1]]
                vote_set.add(comment.author.id)  # .append(comment.author.id)#.add(comment.author.id)
                self.comment_monitor[comment.parent_id.split("_")[-1]] = vote_set
                self.comment_monitor.sync()
                if len(self.comment_monitor[comment.parent_id.split("_")[-1]]) >= \
                        self.monitor_submission[comment.submission.id][0]:
                    del self.comment_monitor[comment.parent_id.split("_")[-1]]
                    self.comment_monitor.sync()
                    while len(self.monitor_submission[comment.submission.id]) < 2:
                        time.sleep(2)
                    add_comment = self.reddit.comment(id=comment.id.split("_")[-1])
                    self.logger.debug("Adding " + add_comment.body + " to spotify playlist " +
                                      self.monitor_submission[comment.submission.id][1])
                    split = add_comment.body.split("by")
                    artist = split[-1].strip()
                    song = split[0].split(" ")[-1]
                    self.task_queue.put(
                        [AddTrack(self.monitor_submission[comment.submission.id][1], artist, song), add_comment])

    def run(self) -> None:
        running = True
        while running:
            try:
                self.monitor_comments()
            except KeyboardInterrupt:
                running = False
                self.logger.debug("Caught key interrupt exception")
            except PrawcoreException as e:
                self.logger.warning("Caught prawcore exception" + str(e))
                time.sleep(10)
