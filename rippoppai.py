"""
oppai interface for ripple 2 / LETS
"""

import subprocess
import os
from helpers import scoreHelper
from helpers import osuapiHelper
from constants import exceptions
from helpers import consoleHelper
from constants import bcolors
from helpers import generalHelper
import score
import beatmap
import argparse
import math
import time
import glob
import threading
import signal

# constants
MAX_WORKERS = 32
MODULE_NAME = "rippoppai"
UNIX = True if os.name == "posix" else False

def fixPath(command):
	"""
	Replace / with \ if running under WIN32

	commnd -- command to fix
	return -- command with fixed paths
	"""
	if UNIX == True:
		return command
	return command.replace("/", "\\")

class oppai:
	"""
	Oppai calculator
	"""
	# Folder where oppai is placed
	OPPAI_FOLDER = "../oppai"

	def __init__(self, __beatmap, __score):
		"""
		Set oppai params.

		__beatmap -- beatmap object
		__score -- score object
		"""
		self.score = __score
		self.beatmap = __beatmap
		self.map = "{}.osu".format(self.beatmap.beatmapID)
		self.acc = self.score.accuracy*100
		self.mods = scoreHelper.readableMods(self.score.mods)
		self.combo = self.score.maxCombo
		self.misses = self.score.cMiss
		self.pp = 0
		self.getPP()

	def getPP(self):
		"""
		Calculate total pp value with oppai and return it

		return -- total pp
		"""
		try:
			# Build .osu map file path
			mapFile = "{path}/maps/{map}".format(path=self.OPPAI_FOLDER, map=self.map)

			try:
				# Check if we have to download the .osu file
				download = False
				if not os.path.isfile(mapFile):
					# .osu file doesn't exist. We must download it
					if glob.debug == True:
						consoleHelper.printColored("[!] {} doesn't exist".format(mapFile), bcolors.YELLOW)
					download = True
				else:
					# File exists, check md5
					if generalHelper.fileMd5(mapFile) != self.beatmap.fileMD5:
						# MD5 don't match, redownload .osu file
						if glob.debug == True:
							consoleHelper.printColored("[!] Beatmaps md5 don't match".format(mapFile), bcolors.YELLOW)
						download = True

				# Download .osu file if needed
				if download == True:
					if glob.debug == True:
						consoleHelper.printRippoppaiMessage("Downloading {} from osu! servers...".format(mapFile))

					# Get .osu file from osu servers
					fileContent = osuapiHelper.getOsuFileFromID(self.beatmap.beatmapID)

					# Make sure osu servers returned something
					if fileContent == None:
						raise exceptions.osuApiFailException(MODULE_NAME)

					# Delete old .osu file if it exists
					if os.path.isfile(mapFile):
						os.remove(mapFile)

					# Save .osu file
					with open(mapFile, "wb+") as f:
						f.write(fileContent.encode("latin-1"))
				else:
					# Map file is already in folder
					if glob.debug == True:
						consoleHelper.printRippoppaiMessage("Found beatmap file {}".format(mapFile))
			except exceptions.osuApiFailException:
				pass

			# Command with params
			command = fixPath("{path}/oppai {mapFile} {acc}% +{mods} {combo}x {misses}xm".format(path=self.OPPAI_FOLDER, mapFile=mapFile, acc=self.acc, mods=self.mods, combo=self.combo, misses=self.misses))
			if glob.debug == True:
				consoleHelper.printRippoppaiMessage("Executing {}".format(command))

			# oppai output
			process = subprocess.run(command, shell=True, stdout=subprocess.PIPE)
			output = process.stdout.decode("utf-8")

			# Last output line - last 2 characters (contains float pp value)
			pp = output.split("\r\n" if UNIX == False else "\n")
			pp = pp[len(pp)-2][:-2]
			self.pp = float(pp)
			return self.pp
		except:
			# oppai or python error, set pp to 0
			consoleHelper.printColored("[!] Error while executing oppai.", bcolors.RED)
			self.pp = 0


if __name__ == "__main__":
	# Standalone imports
	from helpers import config
	from helpers import databaseHelper
	from constants import rankedStatuses
	from helpers import userHelper
	import sys

	# Verbose
	glob.debug = False

	def recalcFromScoreData(scoreData, lock):
		"""
		Recalculate pp value for a score.
		Does every check, output and queries needed.

		score -- score+beatmap dictionary (returned from db with JOIN) of score to recalc
		lock -- shared lock object
		return -- calculated pp value or None
		"""

		# Create score object and set its data
		s = score.score()
		s.setDataFromDict(scoreData)
		if s.scoreID == 0:
			# Make sure the score exists
			if glob.debug == True:
				consoleHelper.printColored("[!] No score with id {}".format(scoreData["id"]), bcolors.RED)

		# Create beatmap object
		b = beatmap.beatmap()

		# Check if we have data for this song
		if scoreData["song_name"] == None:
			# If we don't have song data in scoreData, get with get_scores method (mysql, osuapi blabla)
			lock.acquire()
			b.setData(scoreData["beatmap_md5"], 0)
			lock.release()
		else:
			# If we have data, set data from dict
			b.setDataFromDict(scoreData)

		# Make sure the beatmap is ranked
		if b.rankedStatus != rankedStatuses.RANKED and b.rankedStatus != rankedStatuses.APPROVED and b.rankedStatus != rankedStatuses.QUALIFIED:
			if glob.debug == True:
				consoleHelper.printColored("[!] Beatmap {} is not ranked ().".format(s.fileMd5), bcolors.RED)
			# Don't calculate pp if the beatmap is not ranked
			return False

		# Calculate score pp
		s.calculatePP(b)

		# Update score pp in dictionary
		scoreData["pp"] = s.pp
		return True

	class worker:
		"""
		rippoppai recalculator worker
		"""
		def __init__(self, id, scores, lock):
			"""
			Instantiate a worker

			id -- worker numeric id
			scores -- list of scores+beatmaps dictionaries to recalc
			lock -- shared lock object
			"""
			self.id = id
			self.scores = scores
			self.lock = lock
			self.perc = 0.00
			self.current = 0
			self.total = len(self.scores)
			self.done = False

		def doWork(self):
			"""
			Worker's work
			Basically, calculate pp for scores inside self.scores
			"""

			# Make sure scores have been passed
			if self.scores != None:
				for i in self.scores:
					# Loop through all scores
					# Recalculate pp
					recalcFromScoreData(i, self.lock)

					# Calculate percentage
					self.perc = (100*self.current)/self.total

					# Update recalculated count
					self.current+=1

				# Recalculation finished, save new pp values in db
				consoleHelper.printColored("[WORKER{}] PP calc for this worker finished. Saving results in db...".format(self.id), bcolors.PINK)
				for i in self.scores:
					# Loop through all scores and update pp in db
					# we need to lock the thread because pymysql is not thread safe
					self.lock.acquire()
					glob.db.execute("UPDATE scores SET pp = ? WHERE id = ?", [i["pp"], i["id"]])
					self.lock.release()

			# This worker has finished his work
			self.done = True

	def massRecalc(scores, workersNum = 0):
		"""
		Recalc pp for scores in scores dictionary.

		scores -- dictionary returned from query. must contain id key with score id
		workersNum -- number of workers. If 0, will spawn 1 worker every 200 scores up to MAX_WORKERS
		"""
		# Get total scores number
		totalScores = len(scores)

		# Calculate number of workers if needed
		if workersNum == 0:
			workersNum = min(math.ceil(totalScores/200), MAX_WORKERS)

		# Start from the first score
		start = 0
		end = 0

		# Create lock object and workers list
		lock = threading.Lock()
		workers = []

		# Spawn necessary workers
		for i in range(0,workersNum):
			# Set this worker's scores range
			start = end
			end = start+math.floor(len(scores)/workersNum)
			consoleHelper.printColored("> Spawning worker {} ({}:{})".format(i, start, end), bcolors.PINK)

			# Append a worker object to workers list, passing scores to recalc
			workers.append(worker(i, scores[start:end], lock))

			# Create this worker's thread and start it
			t = threading.Thread(target=workers[i].doWork)
			t.start()

		# Infinite output loop
		while True:
			# Variables needed to calculate percentage
			totalPerc = 0
			scoresDone = 0
			workersDone = 0

			# Loop through all workers
			for i in range(0,workersNum):
				# Get percentage, calculated scores number and done status
				totalPerc += workers[i].perc
				scoresDone += workers[i].current
				if workers[i].done == True:
					workersDone += 1

			# Output global information
			consoleHelper.printColored("> Progress {perc:.2f}% ({done}/{total}) [{donew}/{workers}]".format(perc=totalPerc/workersNum, done=scoresDone, total=totalScores, donew=workersDone, workers=workersNum), bcolors.YELLOW)

			# Exit from the loop if every worker has finished its work
			if workersDone == workersNum:
				break

			# Repeat after 1 second
			time.sleep(1)

	# CLI stuff
	__author__ = "Nyo"
	parser = argparse.ArgumentParser(description="oppai interface for ripple 2 / LETS")
	parser.add_argument('-r','--recalc', help="recalculate pp for every score", required=False, action='store_true')
	parser.add_argument('-z','--zero', help="calculate pp for 0 pp scores", required=False, action='store_true')
	parser.add_argument('-i','--id', help="calculate pp for score with this id", required=False)
	parser.add_argument('-m','--mods', help="calculate pp for scores with this mod (mod id)", required=False)
	parser.add_argument('-u','--userid', help="calculate pp for scores played by a specific user (userID)", required=False)
	parser.add_argument('-n','--username', help="calculate pp for scores played by a specific user (username)", required=False)
	parser.add_argument('-w','--workers', help="force number of workers", required=False)
	parser.add_argument('-v','--verbose', help="run ripp in verbose/debug mode", required=False, action='store_true')
	args = parser.parse_args()

	# Platform
	print("Running under {}".format("UNIX" if UNIX == True else "WIN32"))

	# Load config
	consoleHelper.printNoNl("> Reading config file... ")
	glob.conf = config.config("config.ini")
	glob.debug = generalHelper.stringToBool(glob.conf.config["server"]["debug"])
	consoleHelper.printDone()

	# Connect to MySQL
	try:
		consoleHelper.printNoNl("> Connecting to MySQL db... ")
		glob.db = databaseHelper.db(glob.conf.config["db"]["host"], glob.conf.config["db"]["username"], glob.conf.config["db"]["password"], glob.conf.config["db"]["database"], 0)
		consoleHelper.printDone()
	except:
		consoleHelper.printError()
		consoleHelper.printColored("[!] Error while connection to database. Please check your config.ini and run the server again", bcolors.RED)
		raise

	# Get workers from arguments if set
	workers = 0
	if args.workers != None:
		workers = int(args.workers)

	# Set verbose
	glob.debug = args.verbose

	# Operations
	if args.zero == True:
		# 0pp recalc
		print("> Recalculating pp for zero-pp scores")
		scores = glob.db.fetchAll("SELECT * FROM scores LEFT JOIN beatmaps ON scores.beatmap_md5 = beatmaps.beatmap_md5 WHERE scores.play_mode = '0' AND scores.completed = '3' AND scores.pp = '0' ORDER BY scores.id DESC;")
		massRecalc(scores, workers)
	elif args.recalc == True:
		# Full recalc
		print("> Recalculating pp for every score")
		scores = glob.db.fetchAll("SELECT * FROM scores LEFT JOIN beatmaps ON scores.beatmap_md5 = beatmaps.beatmap_md5 WHERE scores.play_mode = '0' AND scores.completed = '3' ORDER BY scores.id DESC;")
		massRecalc(scores, workers)
	elif args.mods != None:
		# Mods recalc
		print("> Recalculating pp for scores with mods {}".format(args.mods))
		allScores = glob.db.fetchAll("SELECT * FROM scores LEFT JOIN beatmaps ON scores.beatmap_md5 = beatmaps.beatmap_md5 WHERE scores.play_mode = '0' AND scores.completed = '3' ORDER BY scores.id DESC;")
		scores = []
		for i in allScores:
			if i["mods"] & int(args.mods) > 0:
				#consoleHelper.printColored("> PP for score {} will be recalculated (mods: {})".format(i["id"], i["mods"]), bcolors.GREEN)
				scores.append(i)
		massRecalc(scores, workers)
	elif args.id != None:
		# Score ID recalc
		scores = glob.db.fetchAll("SELECT * FROM scores LEFT JOIN beatmaps ON scores.beatmap_md5 = beatmaps.beatmap_md5 WHERE scores.play_mode = '0' AND scores.completed = '3' AND scores.id = ?;", [args.id])
		massRecalc(scores, workers)
	elif args.userid != None:
		# User ID recalc
		username = userHelper.getUsername(args.userid)
		if username != None:
			scores = glob.db.fetchAll("SELECT * FROM scores LEFT JOIN beatmaps ON scores.beatmap_md5 = beatmaps.beatmap_md5 WHERE scores.play_mode = '0' AND scores.completed = '3' AND scores.username = ?;", [username])
			massRecalc(scores, workers)
		else:
			consoleHelper.printColored("[!] User with id {} doesn't exist".format(args.userid), bcolors.RED)
	elif args.username != None:
		# Username recalc
		scores = glob.db.fetchAll("SELECT * FROM scores LEFT JOIN beatmaps ON scores.beatmap_md5 = beatmaps.beatmap_md5 WHERE scores.play_mode = '0' AND scores.completed = '3' AND scores.username = ?;", [args.username])
		massRecalc(scores, workers)

	# The endTM
	consoleHelper.printColored("Done!", bcolors.GREEN)