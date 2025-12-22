<!-- Delete the sections that don't apply -->

### Backwards-incompatible changes

- `config.lab.tmpSource` renamed to `config.lab.emptyDirSource`.

### New features

- A standard homedir provisioner can be run by setting `config.lab.standardInithome` to `true`. It requires that the controller be able to write as an administrative user to the volume containing user home directories.

- `config.lab.homeVolumeName` may be set to tell the controller which volume contains user home directories.

### Other changes

- A standard `startup` initContainer will always be launched in a Lab Pod.
