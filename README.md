# EzRemove Skills

Official [EzRemove](https://ezremove.ai/) image capabilities for AI agents. Each capability is a standalone Skill; all EzRemove Skills can share one private user-level configuration.

## Install

Give your AI coding agent this instruction:

```text
Install EzRemove Skills for me: https://github.com/ezremove/skills.git
```

The agent can install the Skill that matches your task. There is no manual clone or package-install command for you to run.

## Skills

| Skill                        | What it does | Learn more |
|------------------------------| --- | --- |
| `ezremove-remove-background` | Removes a background from a local image or public image URL and returns a transparent PNG. | [Remove Background Skill](https://ezremove.ai/skills/remove-background/) |

## API Key Setup

An API key is optional. Anonymous use has a daily limit. Create a Skill API key in [EzRemove Settings](https://ezremove.ai/settings/), then ask your agent to configure it.

The agent can help you choose one private method:

1. Set `EZ_REMOVE_API_KEY` in the agent runtime environment. This is best for managed environments and CI.
2. Add `EZ_REMOVE_API_KEY=your-key` to `~/.config/ezremove/.env`. If `XDG_CONFIG_HOME` is set, use `$XDG_CONFIG_HOME/ezremove/.env` instead.

The environment variable takes precedence over the file. The user-level `.env` file is shared by every EzRemove Skill, so the key only needs to be configured once. If you ask an agent to create the file, it should first obtain your authorization and must never echo, log, or commit your key. Use [.env.example](.env.example) as a template.

## More from EzRemove

Browse the [EzRemove Skill collection](https://ezremove.ai/skills/) for new capabilities as they are released.

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
