<!-- Delete the sections that don't apply -->

### Backwards-incompatible changes

- `config.lab.tmpSource` renamed to `config.lab.emptyDirSource`. This setting now controls the source for both `/tmp` and the new `/lab/startup`.

### New features

- A standard homedir provisioner can be run by setting `config.lab.standardInithome` to `true`. It requires that the controller be able to write as an administrative user to the volume containing user home directories.

- `config.lab.homeVolumeName` may be set to tell the controller which volume contains user home directories.

### Other changes

- A standard `startup` initContainer will always be launched in a Lab Pod.

- A `/lab_startup` emptyDir volume will always be created for communication between the initContainer fleet and the Lab container.

- At sites where `RSP_SITE_TYPE` is set to `science`, a landing page initContainer will be run to ensure the tutorial landing page is copied into place for the user.
