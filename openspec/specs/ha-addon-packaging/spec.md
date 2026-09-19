## Purpose

Defines Home Assistant add-on packaging standards, multi-process s6-overlay supervision, multi-architecture container builds, versioning conventions, and automated CI/CD release pipelines.

## Requirements

### Requirement: Home Assistant Add-on Repository Conventions
The project SHALL follow Home Assistant's add-on repository layout with `repository.yaml` at root, and add-on descriptors (`config.yaml`, `build.yaml`, `Dockerfile`, `DOCS.md`, `CHANGELOG.md`, `icon.png`, `logo.png`) inside `stridesync/`.

#### Scenario: Add-on store discovery
- **WHEN** the repository URL is added to the Home Assistant Add-on Store
- **THEN** the Home Assistant Supervisor detects and presents StrideSync with its icon, description, and configurable options.

### Requirement: s6-overlay Multi-Service Supervision
The container image SHALL use `ghcr.io/hassio-addons/base` with s6-overlay to run `sync-scheduler` and `mcp-server` as independent supervised services.

#### Scenario: Service fault recovery
- **WHEN** the `sync-scheduler` process terminates due to an unhandled exception
- **THEN** s6-overlay restarts `sync-scheduler` automatically without disrupting the `mcp-server` process.

#### Scenario: Pre-service initialization
- **WHEN** the container boots
- **THEN** scripts in `rootfs/etc/cont-init.d/` execute in order, running database migrations and credential validation before any `services.d` service starts.

### Requirement: Multi-Architecture Build Support
The add-on build system SHALL specify exact base image tags per target architecture (`amd64` and `aarch64`) in `build.yaml`.

#### Scenario: Building for target architecture
- **WHEN** CI or release workflows build the container for `amd64` or `aarch64`
- **THEN** Docker builds using the pinned base image tag defined for that specific architecture in `build.yaml`.

### Requirement: Three-File Semantic Versioning
The project SHALL adhere to the three-file versioning contract across `stridesync/NEXT_VERSION`, `stridesync/config.yaml`, and `stridesync-dev/config.yaml`.

#### Scenario: Development feature PR
- **WHEN** a feature or bug fix is proposed
- **THEN** `stridesync/config.yaml` remains at the last released version while `stridesync-dev/config.yaml` is set to `{NEXT_VERSION}b{N}`.

#### Scenario: Release workflow execution
- **WHEN** the release workflow executes
- **THEN** the tag `v{NEXT_VERSION}` is pushed, images are published, and a post-release PR bumps `NEXT_VERSION` and resets `stridesync-dev/config.yaml`.

### Requirement: CI Pipeline Validation
Every push and pull request SHALL pass automated syntax, linting, version-ordering, and unit test checks enforced by the `ci-pass` status check.

#### Scenario: Pull request submission
- **WHEN** a PR is submitted targeting `main`
- **THEN** GitHub Actions runs yamllint, hadolint, version-ordering checks, Python syntax parsing, and pytest before allowing merge.
