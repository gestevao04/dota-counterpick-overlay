# Releasing

Releases are built by GitHub Actions when you push a version tag.

## Steps

1. Make sure the tests pass: `python -m unittest discover -s tests -t . -v`
   (the `Tests` workflow runs them on every push too).
2. Bump the number in `version.py` (for example `0.1.2`), update the
   "Known limitations" in the README if they changed, and commit.
3. Tag and push. The tag **must** be `v` plus the number in `version.py`, or the
   workflow stops with a message:

   ```
   git tag v0.1.2
   git push origin main --tags
   ```

4. Watch the run in the repository's **Actions** tab. When it finishes, the
   release for the tag has `DotaDraftOverlay-v0.1.2-windows.zip` and its
   `.sha256` attached. If the release did not exist yet, the workflow creates it
   as a pre-release with generated notes.
5. Edit the release: write the notes (what is new, known limitations), and untick
   "pre-release" once you are happy with it.
6. **Test the download on a clean setup** before announcing: unzip it somewhere
   new, run the `.exe`, check that the Settings window opens, a download works,
   and the overlay appears over Dota. The build is checked automatically, but
   nothing replaces seeing it run.

## If the workflow fails

- *Tag does not match version.py*: fix `version.py`, commit, then delete and
  recreate the tag: `git tag -d v0.1.2 && git push origin :refs/tags/v0.1.2`,
  then tag and push again.
- *Tests fail*: fix them first. The build never runs on failing tests.
- *Self-test fails*: the log prints which library is missing from the package.
  Usually it needs an entry in `hiddenimports` in `dota-draft-overlay.spec`.
- You can run the workflow by hand from the Actions tab ("Run workflow") to get
  the build as a downloadable artifact without making a release.

## Later: code signing

Windows SmartScreen and antivirus warnings are the biggest friction for a
downloadable program. Free code signing for open-source projects exists
(SignPath Foundation); it requires fully automated builds, which this workflow
already is. Apply once the project has some users.
