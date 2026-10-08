# Third-party notices

Auto Dev code is licensed under [MIT](LICENSE). The external projects below retain their own licenses and ownership. This repository does not bundle their implementations or binaries. Acknowledgment does not imply endorsement.

## CodeGraph — optional runtime integration

- Upstream: https://github.com/colbymchenry/codegraph
- Package: `@colbymchenry/codegraph`; integration test version: `1.1.0`.
- Author/copyright: Colby Mchenry and upstream contributors; copyright notice below.
- License: [MIT](https://github.com/colbymchenry/codegraph/blob/main/LICENSE).
- Use: Auto Dev invokes the separately installed CLI for code navigation, impact analysis, and index status. Auto Dev's adapter is maintained in this repository; the CodeGraph engine is maintained upstream.
- Distribution: neither CodeGraph source nor binaries are included. Install it separately as described in the README. Its dependencies and their notices remain part of the upstream distribution.

The upstream notice is reproduced here for attribution:

```text
MIT License

Copyright (c) 2026 Colby Mchenry

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## External runtime and development tools

These tools are installed by users or CI, not redistributed in the Auto Dev source release. Follow the license notices that ship with the actual tool version or distribution.

| Project | Role | Upstream license information |
| --- | --- | --- |
| [Python](https://www.python.org/) | Interpreter and standard library; no third-party Python packages are required | [PSF and included-component licenses](https://docs.python.org/3/license.html) |
| [Git](https://git-scm.com/) | Version control, diffs, and worktrees through its CLI | [COPYING](https://github.com/git/git/blob/master/COPYING) |
| [Bash](https://www.gnu.org/software/bash/) | Shell contract tests | [Upstream licensing](https://www.gnu.org/software/bash/#licensing) |
| [ripgrep](https://github.com/BurntSushi/ripgrep) | Search and development contract tests | [MIT or Unlicense](https://github.com/BurntSushi/ripgrep#license) |
| [Node.js](https://nodejs.org/) and [npm](https://github.com/npm/cli) | Installing/running CodeGraph in the integration CI job | [Node.js LICENSE](https://github.com/nodejs/node/blob/main/LICENSE), [npm LICENSE](https://github.com/npm/cli/blob/latest/LICENSE) |
| GitHub Actions: [checkout](https://github.com/actions/checkout), [setup-python](https://github.com/actions/setup-python), [setup-node](https://github.com/actions/setup-node) | CI setup; action code is downloaded by GitHub Actions | Each action's upstream `LICENSE` file |

Codex is the plugin host and is distributed separately by OpenAI under its applicable terms. Other tools named in workflow examples or test fixtures are not installed or bundled by this plugin.

## Contributions involving third-party code

When adding a dependency or copying/modifying upstream material, record its source, version, purpose, and license. Preserve required copyright/license notices and identify modifications. Update these notices if the release starts bundling third-party code or binaries; Auto Dev's MIT license does not replace upstream terms.
