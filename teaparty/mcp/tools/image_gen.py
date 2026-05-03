"""Image generation tools: OpenAI, Flux (BFL), Stability AI."""
from __future__ import annotations

import base64
import os
import time


def _output_path(output_path: str, suffix: str) -> str:
    """Resolve output path, defaulting to a timestamped file in cwd."""
    if output_path:
        return output_path
    ts = int(time.time())
    return os.path.join(os.getcwd(), f'image-{ts}-{suffix}.png')


# ── OpenAI image generation ───────────────────────────────────────────────────

async def image_gen_openai_handler(
    prompt: str,
    model: str = 'gpt-image-1',
    size: str = '1024x1024',
    output_path: str = '',
) -> str:
    """Generate an image using OpenAI's image generation API.

    Requires the OPENAI_API_KEY environment variable.

    Args:
        prompt: Text description of the image to generate.
        model: Model to use — 'gpt-image-1' (default) or 'dall-e-3'.
        size: Image dimensions. For gpt-image-1: '1024x1024', '1024x1536', '1536x1024'.
              For dall-e-3: '1024x1024', '1792x1024', '1024x1792'.
        output_path: Path to write the PNG file. Defaults to a timestamped file in cwd.

    Returns:
        Path to the saved image file.
    """
    import aiohttp

    api_key = os.environ.get('OPENAI_API_KEY', '')
    if not api_key:
        return 'Error: OPENAI_API_KEY environment variable is not set.'

    dest = _output_path(output_path, 'openai')

    payload: dict = {'prompt': prompt, 'model': model, 'n': 1, 'size': size}
    # gpt-image-1 returns b64_json; dall-e-3 can return url or b64_json
    if model == 'gpt-image-1':
        payload['response_format'] = 'b64_json'
    else:
        payload['response_format'] = 'b64_json'

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                'https://api.openai.com/v1/images/generations',
                json=payload,
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json',
                },
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    return f'Error: OpenAI API returned status {resp.status}: {text[:300]}'
                data = await resp.json()
    except Exception as exc:
        return f'Error contacting OpenAI API: {exc}'

    try:
        b64 = data['data'][0]['b64_json']
        img_bytes = base64.b64decode(b64)
    except (KeyError, IndexError, Exception) as exc:
        return f'Error decoding OpenAI response: {exc}'

    try:
        os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
        with open(dest, 'wb') as f:
            f.write(img_bytes)
    except OSError as exc:
        return f'Error writing image to {dest!r}: {exc}'

    return dest


# ── Flux (Black Forest Labs) ──────────────────────────────────────────────────

async def image_gen_flux_handler(
    prompt: str,
    width: int = 1024,
    height: int = 1024,
    output_path: str = '',
) -> str:
    """Generate an image using Black Forest Labs' Flux API.

    Requires the BFL_API_KEY environment variable.
    Register at https://api.bfl.ml/ to obtain a key.

    Args:
        prompt: Text description of the image to generate.
        width: Image width in pixels (default 1024).
        height: Image height in pixels (default 1024).
        output_path: Path to write the PNG file. Defaults to a timestamped file in cwd.

    Returns:
        Path to the saved image file.
    """
    import aiohttp
    import asyncio

    api_key = os.environ.get('BFL_API_KEY', '')
    if not api_key:
        return 'Error: BFL_API_KEY environment variable is not set.'

    dest = _output_path(output_path, 'flux')
    headers = {'x-key': api_key, 'Content-Type': 'application/json'}

    # Submit generation request
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                'https://api.bfl.ml/v1/flux-pro-1.1',
                json={'prompt': prompt, 'width': width, 'height': height},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    return f'Error: Flux API returned status {resp.status}: {text[:300]}'
                submit_data = await resp.json()

            request_id = submit_data.get('id')
            if not request_id:
                return f'Error: Flux API returned no request ID: {submit_data}'

            # Poll for result
            poll_url = f'https://api.bfl.ml/v1/get_result?id={request_id}'
            for _ in range(60):  # up to ~60 seconds
                await asyncio.sleep(1)
                async with session.get(
                    poll_url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    result = await resp.json()
                    status = result.get('status')
                    if status == 'Ready':
                        image_url = result.get('result', {}).get('sample')
                        break
                    elif status in ('Error', 'Failed', 'Content Moderated'):
                        return f'Error: Flux generation failed with status {status!r}.'
            else:
                return 'Error: Flux generation timed out after 60 seconds.'

            # Download image
            async with session.get(
                image_url,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    return f'Error: Could not download Flux image (status {resp.status})'
                img_bytes = await resp.read()

    except Exception as exc:
        return f'Error during Flux image generation: {exc}'

    try:
        os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
        with open(dest, 'wb') as f:
            f.write(img_bytes)
    except OSError as exc:
        return f'Error writing image to {dest!r}: {exc}'

    return dest


# ── Stability AI ──────────────────────────────────────────────────────────────

async def image_gen_stability_handler(
    prompt: str,
    aspect_ratio: str = '1:1',
    output_path: str = '',
) -> str:
    """Generate an image using Stability AI's Stable Image Core API.

    Requires the STABILITY_API_KEY environment variable.
    Register at https://platform.stability.ai/ to obtain a key.

    Args:
        prompt: Text description of the image to generate.
        aspect_ratio: Output aspect ratio — '1:1', '16:9', '9:16', '4:3', '3:4', '21:9'.
        output_path: Path to write the PNG file. Defaults to a timestamped file in cwd.

    Returns:
        Path to the saved image file.
    """
    import aiohttp

    api_key = os.environ.get('STABILITY_API_KEY', '')
    if not api_key:
        return 'Error: STABILITY_API_KEY environment variable is not set.'

    dest = _output_path(output_path, 'stability')

    try:
        form = aiohttp.FormData()
        form.add_field('prompt', prompt)
        form.add_field('aspect_ratio', aspect_ratio)
        form.add_field('output_format', 'png')

        async with aiohttp.ClientSession() as session:
            async with session.post(
                'https://api.stability.ai/v2beta/stable-image/generate/core',
                data=form,
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Accept': 'image/*',
                },
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    return f'Error: Stability API returned status {resp.status}: {text[:300]}'
                img_bytes = await resp.read()

    except Exception as exc:
        return f'Error contacting Stability AI API: {exc}'

    try:
        os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
        with open(dest, 'wb') as f:
            f.write(img_bytes)
    except OSError as exc:
        return f'Error writing image to {dest!r}: {exc}'

    return dest
