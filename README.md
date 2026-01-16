# Blog (Jekyll)

This folder contains a minimal Jekyll blog for ggblab. It is separate from `docs/` (which is used by ReadTheDocs).

To preview locally (requires Ruby + Bundler + Jekyll):

```bash
gem install bundler jekyll
cd blog
jekyll serve --source .
# open http://127.0.0.1:4000
```

When you push to GitHub, GitHub Pages will build the site automatically if Pages is configured to build from the repository (usually `gh-pages` branch or `/ (root)` or `/docs`). If you want GitHub Pages to serve the `blog/` directory as the site source, configure Pages in the repository settings accordingly.
