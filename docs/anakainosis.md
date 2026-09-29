# Anakainosis
### *Cleaning up the codebase*

> Note: This is a work in progress. The codebase is still being cleaned up and organized. Please check back later for updates.

> NON-AI NOTICE: This file doesn't contain any AI-generated content. It is written by a human.

## What is Anakainosis?
Anakainosis is a Greek word that means "renewal" or "revitalization."
The local codebase that I, mrt-tak, have has been cluttered code all over the place. I have decided to clean it up and make it more organized and readable. This process is called Anakainosis.
As of now (27.9.2026), we are still working on cleaning it up. Currently the code in git branch `deploy/PROD` is the best codebase for you to fork off or contribute to as it is the most stable, clean and useful codebase that goes straight into the point.

## What are the rules of Anakainosis?
The main log that deals with Roblox group and it's users' roles are in the app.py, along with other crucial parts of the Discord bot.
All others should be placed outside ``app.py`` and into their own files. Any reuseable code should also be placed outside ``app.py``, for Discord bot or Roblox related code, it can also be placed into ``utils.py``. 

### Examples:
* Key logic on Roblox group and its users' roles - leave it to ``app.py``
* logging - leave it to ``logging_setup.py``
* commands - leave it to ``commands.py``.