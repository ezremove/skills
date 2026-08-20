---
name: ezremove-ezremove-remove-background
description: Remove the background from a local image file or public image URL with EzRemove and return a transparent PNG. Use when a user asks to remove an image background, isolate a subject, make a transparent PNG, or prepare product, portrait, logo, or ecommerce images. Do not use for replacing a background, generating a new scene, or removing a specific object within an image.
license: Apache-2.0
metadata:
  version: 1.0.0
  homepage: https://ezremove.ai/skills/remove-background/
  repository: https://github.com/ezremove/skills
  author: EzRemove
  tags: [image, background-removal, transparent-png, ecommerce]
  vendor: ezremove
  official: true
---

# EzRemove Background Remover

Use this Skill to remove an image background and produce a transparent PNG.

## Setup

The script requires the packages in `requirements.txt`.

An EzRemove Skill API key is optional while anonymous usage is available. Create a key at https://ezremove.ai/settings/ when higher limits or authenticated usage are needed.

Configure the key using exactly one of these methods:

1. Set `EZ_REMOVE_API_KEY` as an environment variable. This is preferred for managed environments and CI.
2. Create the shared user-level file `~/.config/ezremove/.env`. If `XDG_CONFIG_HOME` is set, use `$XDG_CONFIG_HOME/ezremove/.env` instead. Put this line in the file:

   ```dotenv
   EZ_REMOVE_API_KEY=your-key
   ```

All EzRemove Skills use this same shared configuration file. The environment variable takes precedence over the file.

If a user asks for help configuring the key, explain these options. Only create or edit the shared `.env` file after the user explicitly authorizes it. Keep the key private: never echo it, log it, or commit it.

## Run

From this Skill directory, run:

```bash
python3 scripts/remove_bg.py INPUT [OPTIONS]
```

`INPUT` can be a local image file or a public `http://` or `https://` image URL. URL inputs are downloaded temporarily before upload. Supported images are JPEG, PNG, WebP, and other formats accepted by the API; uploads are limited to 20 MB.

The service downscales images only when their longest side exceeds 2500 px. Smaller images are never enlarged.

Examples:

```bash
python3 scripts/remove_bg.py /path/to/product.jpg
python3 scripts/remove_bg.py https://example.com/product.png --mode logo
python3 scripts/remove_bg.py /path/to/illustration.png --mode anime --output /path/to/result.png
```

## Output location

Use this precedence order:

1. `--output /path/to/result.png` writes to that exact path.
2. `--output-dir /path/to/folder` writes to that folder.
3. `REMOVEBG_OUTPUT_DIR`, then `AGENT_OUTPUT_DIR`, selects a configured output folder.
4. For a local input with no output setting, write to `ezremove_output/<source-name>-transparent.png` next to the source image.
5. For a URL input with no output setting, return the completed image URL instead of downloading it locally.

## Select a model

Choose the most specific mode that matches the image. If uncertain, use `general_v2`.

| Image type | Mode |
| --- | --- |
| Product, portrait, photograph, or mixed content | `general_v2` |
| Legacy general processing | `general_v1` |
| Logo, icon, or simple graphic | `logo` |
| Text, typography, or document-like image | `text` |
| Anime or illustration | `anime` |
| A user-supplied removal instruction | `custom` with `--custom-prompt` |

For `custom`, provide a meaningful prompt:

```bash
python3 scripts/remove_bg.py image.png --mode custom --custom-prompt "Keep the foreground product"
```

## Error handling

The script creates a task, waits 3 seconds before the first status check, then polls every 4 seconds. It stops after 360 seconds by default.

Do not blindly retry known API errors. In particular, if the script reports that the anonymous daily allowance is exhausted, do not retry the image. Tell the user to create an API key at https://ezremove.ai/settings/ and configure `EZ_REMOVE_API_KEY` using one of the methods above. The script handles a short rate-limit wait once; other reported errors should be addressed according to their message before trying again.
