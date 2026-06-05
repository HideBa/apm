# APM Packages

A collection of [APM](https://microsoft.github.io/apm/) (Agent Package Manager) projects I use for different purposes. Each folder is a standalone APM project with its own `apm.yml` bundling the skills, plugins, and tools for that workflow.

| Package | Purpose |
| --- | --- |
| [`app-dev`](./app-dev) | Application development (Rust / TypeScript / Python / C++ LSPs, frontend, Playwright). |
| [`library-dev`](./library-dev) | Library development (modernization, simplifier, ralph-loop, LSPs). |
| [`learn`](./learn) | Learning workflows (explanatory & learning output styles). |
| [`research`](./research) | Reading and writing research papers (academic-research-skills). |

## Install

Make sure the [`apm` CLI](https://microsoft.github.io/apm/) is installed first.

Then install any package straight from this repo by referencing its subdirectory — no need to clone:

```bash
apm install HideBa/apm/app-dev      # or library-dev, learn, research
```

This fetches the package's `apm.yml`, resolves its dependencies, and deploys them to your agent harness (Claude Code, Cursor, etc.).

Pin to a specific commit or tag to avoid drift:

```bash
apm install HideBa/apm/research#main
```

### Other options

```bash
apm install HideBa/apm/research --target claude   # deploy to a specific harness
apm install HideBa/apm/research --dry-run         # preview without writing
apm install -g HideBa/apm/research                # install to user (global) scope
```

See the [official install guide](https://microsoft.github.io/apm/consumer/install-packages/) for the full reference.
