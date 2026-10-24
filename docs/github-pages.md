# Publish the public website with GitHub Pages

This repository includes `.github/workflows/pages.yml`. On each push to main (or a manual workflow run), it builds a static website and deploys only `dist/pages`. The workflow needs no AWS credentials, provider keys or Python dependencies beyond the standard library. The public site includes the home page/video, searchable 64-agent library, console setup instructions, downloadable console ZIP and all agent ZIPs. Downloadable packages include Apache 2.0 licensing. Python APIs, saved evaluation history and the interactive evaluator are not hosted by Pages.

## Enable deployment

1. Push the workflow and builder files to main.
2. In repository Settings → Pages, change Source from Deploy from a branch to **GitHub Actions**. Do not choose main/root as the Pages publishing directory.
3. Keep your existing custom domain in Pages settings. With Actions, GitHub stores the domain setting; the builder does not need to guess or write a CNAME file.
4. In Actions, select Publish website to GitHub Pages and check that build and deploy succeed. If necessary select Run workflow → main.
5. Wait for your DNS check and certificate provisioning, then enable Enforce HTTPS.

The configure-pages action provides the base path automatically. A custom domain uses `/`; the default project address uses `/opencaliber/`. Directory index pages provide clean `/agents/` and `/console/` URLs. Legacy agents.html and console.html addresses redirect to those pages.

## Build locally

```sh
python -m unittest discover -s tests -p test_pages.py -v
python tools/build_pages.py
python -m http.server 8080 --directory dist/pages
```

Open http://127.0.0.1:8080/. The builder requires an empty output directory; to build again choose a fresh subdirectory, for example `--output dist/pages-preview`. For project-path output use `--base-path /opencaliber` and serve its parent with the output directory named opencaliber.

Console setup explains how to download, start and integrate the evaluator. It does not pretend to run evaluations on GitHub Pages. Home download buttons point to a ZIP built during the workflow, so a separate GitHub Release is optional. Public agent downloads are built from the tracked templates on every deployment.

Generated site files, ZIPs and evaluation databases remain ignored by Git. The workflow uploads the generated static site rather than the entire repository.
