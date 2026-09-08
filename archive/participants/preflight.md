# Prepare for the workshop

> Archived material. Follow the [workshop README](../../README.md) for the current activity.

Complete this before the session. You need a browser, internet access, and a
terminal that runs Git and Python 3.10 or later. The commands below work in
Cloud Shell or a macOS/Linux terminal. On Windows, use Cloud Shell or WSL for
the same commands. Your facilitator supplies your team's service URL and token.

A **terminal** runs typed commands. The **URL** identifies your team's service.
The **token** is a credential that permits viewing settings and changing them;
keep it out of shared notes, screenshots, and public repositories.

## Set up the command-line tool

Run these commands one line at a time. If you already have the repository,
enter its directory and continue from the environment creation step.

```bash
git clone https://github.com/anh-nguyen28/adsc-workshop.git
cd adsc-workshop
python3 -m venv .participant-venv
.participant-venv/bin/python -m pip install httpx==0.28.1
export PATH="$PWD/.participant-venv/bin:$PWD/cli:$PATH"
```

The clone downloads the workshop files. The virtual environment keeps its Python
dependency separate from other projects. `httpx` sends web requests, and `PATH`
lets your terminal find the `nimbus` command and its Python environment.
No model weights, Docker installation, or Google model credentials are needed.

Replace the two placeholders below with the values your facilitator supplies:

```bash
nimbus init https://YOUR-TEAM-SERVICE.run.app YOUR-TEAM-TOKEN
nimbus brief
nimbus status
```

You are ready when `brief` prints your incident and targets, and `status` prints
the service settings. `init` checks service health but does not validate your
token; `status` checks authenticated access. Leave the settings as they are.

`init` stores credentials in a private `~/.nimbus.json` and starts a new session.
Run history is kept separately for each service and session. Continue using the
same terminal during the activity. In a new terminal, return to the repository
directory and repeat the `export PATH=...` line; another `init` starts new history.

## If a step fails

| What you see | What to do |
| --- | --- |
| `python3` or `git` is unavailable | Use Cloud Shell or pair with a teammate |
| Environment creation or installation fails | Ask a facilitator; use a working teammate's terminal while they check setup |
| `nimbus: command not found` | Return to the repository directory and repeat the `export PATH=...` line |
| A message asking you to run `nimbus init` | Run `init` on this machine with your team's URL and token |
| A health warning or connection error | Check the URL with your facilitator |
| `That token was not accepted` | Check that the URL and token belong to the same team |

One teammate operates the terminal while others interpret results and record
evidence. Only one person should send benchmark or evaluation traffic at a time.
Next, read [the concepts](concepts.md), then open [the investigation guide](quickstart.md).
