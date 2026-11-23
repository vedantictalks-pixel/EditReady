# EditReady

A free, open-source video downloader made for video editors. Paste a link from YouTube, Instagram, Vimeo, X, Facebook or 1,000+ other sites and click Download. EditReady grabs the highest quality the site offers and saves a file that Premiere Pro and After Effects open straight away.

It's a normal app for Mac, Windows and Linux. Nothing else to install.

## Download

Go to this project's **Releases** page and pick the file for your computer:

| Your computer | File |
|---|---|
| Mac with Apple chip (M1, M2, M3, M4 and newer) | EditReady-Mac-AppleSilicon.dmg |
| Mac with Intel chip | EditReady-Mac-Intel.dmg |
| Windows 10 or 11 | EditReady-Setup-Windows.exe |
| Windows, no install | EditReady-Windows-Portable.zip |
| Linux (64-bit) | EditReady-Linux-x64.tar.gz |

Not sure which Mac you have? Apple menu → **About This Mac**. "Chip: Apple" means Apple chip.

**First open on Mac.** Open the .dmg and drag EditReady into Applications. The first time you open it, macOS says it can't check the app. Go to **System Settings → Privacy & Security**, scroll down and click **Open Anyway**. You only do this once.

**First open on Windows.** Run the setup file. If SmartScreen appears, click **More info → Run anyway**. You only do this once.

**Linux.** Extract the archive and run `EditReady/EditReady`. It opens in your web browser.

These one-time warnings appear because the app isn't signed with a paid Apple or Microsoft developer certificate. The full source code is here for anyone to check.

## Using it

1. Paste one or more links (one per line).
2. Choose where to save. An external drive works fine.
3. Click **Download**, or press Ctrl+Enter (Cmd+Enter on Mac).

Files are named like `Video title [2160p60].mov`, and nothing gets overwritten. Click **Show file** next to a finished download to find it.

**Options** (click to open) lets you change the format, cap the quality, download whole playlists, or use your browser's login for private videos.

## What format you get

| Format option | Result |
|---|---|
| Best for Premiere & After Effects (default) | H.264 videos are repacked as MP4 with no quality loss. Anything else (VP9, AV1, which YouTube uses for 1440p and 4K) becomes ProRes 422 HQ .mov. |
| ProRes 422 HQ (.mov) | Always ProRes. Smoothest editing, especially in After Effects. |
| H.264 (.mp4) | Smaller files. Works well in Premiere, slower in After Effects. |
| Audio only (.wav) | The best audio track as WAV. |

ProRes files are large: about 1.6 GB per minute at 1080p30, 5 GB per minute at 4K30 and 13 GB per minute at 4K60. EditReady checks free space first and tells you if the drive is too full.

No tool can give you the exact file the creator uploaded, because sites re-compress every upload. EditReady gets the best version the site serves.

## Updates

Sites like YouTube change often. EditReady checks for a new download engine about once a day and downloads it by itself. When one is ready, you'll see a note; close and reopen EditReady to use it. You can also click **Check for updates** at the bottom.

## Troubleshooting

**"YouTube asked to confirm you're not a bot."** Open Options, pick your browser under "Use logins from", and make sure you're signed in to YouTube in that browser.

**Error 403, or only low qualities.** Click **Check for updates**, then close and reopen EditReady.

**Private or members-only videos.** Use "Use logins from" with a browser where you're signed in. Firefox works most reliably. On Windows, close Chrome or Edge completely first.

**Something else.** EditReady keeps a log at `.editready/editready.log` in your home folder.

To uninstall, delete the app and the hidden `.editready` folder in your home folder.

---

## For the maker: publish the apps (free)

GitHub builds the Mac, Windows and Linux apps for you on its free build machines. You don't need a Windows PC or any coding.

**One-time setup**

1. Create a free account at github.com.
2. Install **GitHub Desktop** (desktop.github.com) and sign in.
3. In GitHub Desktop: **File → Add Local Repository**, choose this EditReady folder, and click **create a repository** when it offers. Then click **Publish repository** and untick "Keep this code private".

GitHub Desktop includes the hidden `.github` folder automatically. That folder holds the build instructions.

**Make a release (every time you want new downloads)**

1. On your repository's page on github.com, click **Releases → Draft a new release**.
2. Under "Choose a tag", type a version like `v1.0.0` and click **Create new tag**.
3. Give it a title and click **Publish release**.

GitHub then builds everything, which takes about 15 to 25 minutes. You can watch it on the **Actions** tab. Each app runs a self-test before its files are attached to the release. When it finishes, the Releases page has all the download files and instructions. Share that page's link with anyone.

To test a build without publishing, open the **Actions** tab, pick **Build apps**, and click **Run workflow**. The files appear at the bottom of that run's page.

When you change the app later, bump `APP_VERSION` in `app.py`, commit and push in GitHub Desktop, then make a new release.

## For developers: run from source

Needs Python 3.11+. Double-click **Start EditReady (Mac).command** or **Start EditReady (Windows).bat**, or run `bash start-linux.sh`. The first start installs the engine into `~/.editready/venv`.

To build the app yourself: `pip install -r packaging/requirements-build.txt -r packaging/requirements-window.txt`, then `python -m PyInstaller --noconfirm --clean packaging/EditReady.spec`. Check a build with `EditReady --selftest`.

## Please use it responsibly

Download only videos you own or have permission to use, such as your own uploads, your company's content, or licensed footage. Downloading other people's videos can break a site's terms of service and copyright law.

## Built with

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) for downloading (Unlicense)
- [yt-dlp-ejs](https://github.com/yt-dlp/ejs) and [Deno](https://deno.com) for YouTube's JavaScript checks (MIT and ISC)
- [FFmpeg](https://ffmpeg.org), from [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) builds (GPL)
- [pywebview](https://pywebview.flowrl.com) for the app window, [PyInstaller](https://pyinstaller.org) and [Inno Setup](https://jrsoftware.org/isinfo.php) for packaging

EditReady itself is MIT licensed. Anyone can use, change and share it.
