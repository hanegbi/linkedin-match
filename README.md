# LinkedIn Match

This is a Claude Code skill. It looks at your LinkedIn connections and your CV,
then finds open jobs at companies where you already know someone who works
there. It can give you a quick ranked list, or a full HTML report where each
job is scored against your CV by Claude.

Everything runs on your own machine. Nothing is sent to a third party, and no
API key is needed.

## Step 1: Get your LinkedIn connections file

The skill needs a file called `Connections.csv`, which LinkedIn will generate
for you. Here's how to get it:

1. Log in to [linkedin.com](https://www.linkedin.com).
2. Go directly to the [Get a copy of your data](https://www.linkedin.com/mypreferences/d/download-my-data) page. If that link does not work for you, click your profile picture in the top right, choose "Settings & Privacy", open the "Data privacy" tab, then click "Get a copy of your data".
3. Choose "Want something in particular? Select the data files you're most interested in", then check just "Connections". This makes LinkedIn prepare it in a few minutes instead of up to a day.
4. Click "Request archive". LinkedIn will confirm your password and start preparing the file.
5. Wait for the email from LinkedIn (usually a few minutes), then come back to the same page and download the file.
6. Unzip it. Inside you'll find `Connections.csv`. Keep it somewhere you'll remember, like a new folder for your job search.

You'll also want your CV as a Word or PDF file. Keep it in that same folder.

## Step 2: Install the skill

Open Claude Code and run these two commands:

```
/plugin marketplace add hanegbi/linkedin-match
/plugin install linkedin-match@linkedin-match
```

That's it. Nothing to build, nothing to configure ahead of time.

## Step 3: Run it

In a Claude Code chat, type:

```
/linkedin-match
```

Claude will ask where your `Connections.csv` and CV are, ask which job titles
you're interested in, and then do the rest: scrape open jobs, match them
against your connections, and build the report. The first time it runs, it
quietly sets up its own Python environment, so it may take a minute before you
see progress.

## License

MIT. Full terms are in [LICENSE.txt](LICENSE.txt).
