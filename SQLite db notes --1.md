`illuminate.db` changes because it is the SQLite database used by the Flask app. Every new registration inserts a user record, so SQLite updates the file.

Yes, adding it to `.gitignore` is correct:

```gitignore
illuminate.db
generated_qr/
```

However, `.gitignore` does not stop the file from changing locally. It only prevents Git from tracking new changes to that file.

Important distinction:

- Local database behavior: continues normally.
- Git status: ignores database modifications.
- Existing tracked database: `.gitignore` will not untrack it automatically.

If it was already committed, run:

```powershell
git rm --cached illuminate.db
git commit -m "Ignore local database files"
```

After that, registrations will still modify `illuminate.db` locally, but Git will ignore those modifications.
