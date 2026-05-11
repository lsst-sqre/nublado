### Backwards-incompatible changes

- jupyterlab-base requires a newer set of Lab extensions, which remove the "Save All" items from the File menu, leaving only "Exit" and "Logout": the new version continually autosaves so explicit saving is ineffectual.

### New features

- jupyterlab-base now uses jupyter-server-documents to continually autosave.
