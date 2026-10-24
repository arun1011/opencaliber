# Publish this repository

1. Review all staged files and confirm you own or may publish the included material. Review LICENSING.md, especially walkthrough media and branding.
2. Create an empty repository named opencaliber under your personal GitHub account. Start private if you want a final review before making it public.
3. From THIS folder, initialize a fresh Git repository. No existing Git history or remote was copied.

```sh
git init
git branch -M main
git add .
git status
# Review git diff --cached before committing.
git commit -m "Initial open-source release"
git remote add origin https://github.com/YOUR-USERNAME/opencaliber.git
git push -u origin main
```

4. Enable private vulnerability reporting in GitHub repository security settings.
5. Run `python tools/build_agent_library.py` after a fresh clone; generated ZIPs are ignored by Git. Verify installation and tests in a fresh checkout, then make the repository public when ready.
6. Build the ZIPs with the README commands and attach the console package to a v0.1.0 GitHub Release. Add the EB source bundle only if useful for users deploying to AWS.
7. Add the repository URL to the website and your professional profile. No GitHub account name, remote or employer identity has been guessed here.

The prepared directory has no .git history, databases, credentials, trained weights or local evaluation output. This preparation is not a substitute for reviewing the files before upload. No repository was created online or pushed automatically.
