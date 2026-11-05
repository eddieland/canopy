# Dictation

Talk instead of typing: a microphone on every reply box, turned into text by a speech model you run on the loop's own
machine. This page covers setting it up, using it from another computer, and what it never does with your voice.

## What it does

Once it's set up, every text box with a formatting toolbar gets a **Dictate** button at the end of the toolbar:
replies to a ticket, messages to a running worker, a task's text, notes on a plan. Press it, talk, and press it again.
A clock beside the button counts what you've recorded; a spinner means the loop's machine is listening back.

What it heard goes in where your cursor was, as one edit, so ⌘Z (Ctrl+Z) takes it back. Nothing is sent: the text
sits in the box until you've read it and pressed send yourself. A speech model is very good and occasionally very
confident about a word you never said, and the box is where you catch it.

- A recording runs for up to 4 minutes 50 seconds, then stops by itself and is transcribed. Longer thoughts take two
  presses.
- One recording is transcribed at a time. A second, while the first is still with the model, is refused as `busy`.
- canopy gives the model a hint of the words it should expect: your repositories' names, then the keys and titles of
  the tickets canopy is working on, the most recently changed first. That's the difference between `PROJ-142` and
  "project one four two".

## Setting it up

Dictation runs a command you choose, on the machine where `canopy loop` runs. The command reads a recording and prints
what was said. canopy ships no model; [whisper.cpp](https://github.com/ggml-org/whisper.cpp) is a good one, runs on a
CPU, and needs no service.

On the loop's machine, build it and fetch a model:

```sh
git clone https://github.com/ggml-org/whisper.cpp ~/src/whisper.cpp
cd ~/src/whisper.cpp
cmake -B build
cmake --build build -j --config Release
sh ./models/download-ggml-model.sh large-v3-turbo
```

`large-v3-turbo` is the most accurate of the ones that keep up with speech on a recent CPU. On a small machine,
`small.en` or `base.en` are quicker and a little less sure of your jargon; the vocabulary hint helps them most.

Then name the command in your private config, `~/.config/canopy/config.toml` or the workspace's own, and reload the
loop: **Reload** in [Settings](settings#config), or `kill -HUP` on its pid.

```toml
[serve]
dictation_cmd = """\
    /home/you/src/whisper.cpp/build/bin/whisper-cli \
    -m /home/you/src/whisper.cpp/models/ggml-large-v3-turbo.bin \
    -nt -np -sns -l en -f {audio} --prompt {vocabulary}"""
```

- The `\` that ends each line joins the lines into one command; a single line in quotes works as well.
- `{audio}` is the recording's path, and must be there exactly once: a 16-bit mono WAV at 16 kHz, which canopy has
  already checked.
- `{vocabulary}` is optional: the words to expect, as one argument.
- No shell runs it, so `~` and `$HOME` mean nothing: write whole paths.
- For whisper-cli, `-nt` drops the timestamps, `-np` the progress, and `-sns` the non-speech tokens such as `[Music]`.
  `-l en` skips guessing the language; leave it out if you switch between languages.

Any program will do that reads the WAV at `{audio}`, prints the text, and exits 0. A script that sends the
recording to a hosted service works too, and sends your voice there; that's between you and the service. The command
gets 3 minutes before it's stopped.

The key is private: the shared workspace file can't set it, since it runs a command. Nor can the
[Settings](settings#limits-and-trust) page, for the same reason. Unset, no box shows a microphone.

## From another computer

A browser lets a page use the microphone only over HTTPS or on `localhost`. When the loop runs on one machine and your
browser on another, say a Linux box and your Mac, open the UI through an SSH forward, which makes it `localhost` to the
browser:

```sh
ssh -N -L 8765:127.0.0.1:8765 you@loop-host
```

Then open `http://localhost:8765`. The first press of **Dictate** asks whether the page may use the microphone; allow
it. On a Mac, the browser itself also needs it: System Settings, Privacy & Security, Microphone. If notifications
should open the UI the same way, set `serve.url` to `http://localhost:8765/`.

Over plain HTTP to another host's address, the button is there but greyed out, and its tip says why. The browser isn't
being difficult; it's declining to hand your microphone to anyone on the network who can pretend to be that address.

## When it doesn't work

What went wrong shows under the box, named as the CLI names a refusal:

- `bad_audio`: the recording wasn't the WAV canopy takes, or it was empty. A browser that records in a format it
  can't play back fails here too, and says so.
- `busy`: another recording is still being transcribed.
- `failed`: the command isn't on the loop's `PATH`, or exited with an error. The end of what it printed to stderr comes
  with it, which usually names the model file it couldn't find.
- `timed_out`: the command took longer than 3 minutes. Pick a smaller model, or say less.
- `off`: there's no command set, or the loop hasn't been reloaded since you set it.

A box with no microphone at all means the server offers no dictation: set the key and reload.

## What it never does

Your words go back to the box you recorded into and nowhere else. The journal and the log record that a recording was
transcribed, how long it was, and how many characters came back; never the audio or the text. The recording lives in
a private temporary directory for as long as the command runs, and is deleted when it ends. What you send afterwards
is recorded as anything you type is.
