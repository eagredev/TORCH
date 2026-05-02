/**
 * TORCH Web GUI -- Sprite processing utilities.
 * Handles two-frame spritesheet clipping and background colour removal
 * for any view that displays Pokemon sprites (Dex, Encounters, Trainers, etc.).
 */

const spriteCache = new Map();
const spriteFrameCache = new Map();
const CACHE_MAX_SIZE = 200;

/** Evict oldest half of a Map when it exceeds CACHE_MAX_SIZE entries. */
function _evictIfNeeded(cache) {
  if (cache.size <= CACHE_MAX_SIZE) return;
  const keysToDelete = [...cache.keys()].slice(0, Math.floor(cache.size / 2));
  for (const k of keysToDelete) cache.delete(k);
}

/** Clear both sprite caches. Call during view cleanup to free memory. */
export function clearCaches() {
  spriteCache.clear();
  spriteFrameCache.clear();
}

const FALLBACK_SVG = "data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2296%22 height=%2296%22><circle cx=%2248%22 cy=%2248%22 r=%2240%22 fill=%22%23333%22/><text x=%2248%22 y=%2254%22 text-anchor=%22middle%22 fill=%22%23666%22 font-size=%2212%22>?</text></svg>";

/**
 * Process a Pokemon sprite: clip to first frame, remove background colour.
 * Returns a Promise<string> that resolves to a data URL of the cleaned sprite.
 * Results are cached -- calling processSprite with the same URL returns the cached result.
 */
export async function processSprite(spriteUrl) {
  if (spriteCache.has(spriteUrl)) return spriteCache.get(spriteUrl);

  _evictIfNeeded(spriteCache);

  // Create a promise and cache it immediately to avoid duplicate processing
  const promise = _doProcess(spriteUrl);
  spriteCache.set(spriteUrl, promise);

  try {
    const result = await promise;
    spriteCache.set(spriteUrl, result);
    return result;
  } catch {
    spriteCache.delete(spriteUrl);
    return FALLBACK_SVG;
  }
}

async function _doProcess(spriteUrl) {
  const img = await _loadImage(spriteUrl);

  const srcW = img.naturalWidth;
  const srcH = img.naturalHeight;
  if (srcW <= 0 || srcH <= 0) return FALLBACK_SVG;
  // Two-frame spritesheets are exactly 2x height (64x128). Single-frame
  // sprites (megas, gmax, some forms) are square (64x64). Only clip if
  // the image is taller than wide.
  const frameH = srcH > srcW ? Math.floor(srcH / 2) : srcH;

  const canvas = document.createElement("canvas");
  canvas.width = srcW;
  canvas.height = frameH;
  const ctx = canvas.getContext("2d");

  // Draw only the top frame
  ctx.drawImage(img, 0, 0, srcW, frameH, 0, 0, srcW, frameH);

  // Remove background colour
  try {
    const imageData = ctx.getImageData(0, 0, srcW, frameH);
    const data = imageData.data;

    // Sample background colour from pixel (0, 0)
    const bgR = data[0];
    const bgG = data[1];
    const bgB = data[2];

    const TOLERANCE = 2;
    for (let i = 0; i < data.length; i += 4) {
      if (Math.abs(data[i]     - bgR) <= TOLERANCE &&
          Math.abs(data[i + 1] - bgG) <= TOLERANCE &&
          Math.abs(data[i + 2] - bgB) <= TOLERANCE) {
        data[i + 3] = 0; // Set alpha to transparent
      }
    }

    ctx.putImageData(imageData, 0, 0);
  } catch {
    // CORS or other canvas security error -- return clipped but unprocessed
  }

  return canvas.toDataURL("image/png");
}

/**
 * Extract both frames from a two-frame spritesheet.
 * Returns { frame1: dataUrl, frame2: dataUrl|null }.
 * frame2 is null for single-frame sprites (height <= width).
 * Results are cached by URL.
 */
export async function processSpriteFrames(spriteUrl) {
  if (spriteFrameCache.has(spriteUrl)) return spriteFrameCache.get(spriteUrl);

  _evictIfNeeded(spriteFrameCache);

  const promise = _doProcessFrames(spriteUrl);
  spriteFrameCache.set(spriteUrl, promise);

  try {
    const result = await promise;
    spriteFrameCache.set(spriteUrl, result);
    return result;
  } catch {
    spriteFrameCache.delete(spriteUrl);
    return { frame1: FALLBACK_SVG, frame2: null };
  }
}

async function _doProcessFrames(spriteUrl) {
  const img = await _loadImage(spriteUrl);
  const srcW = img.naturalWidth;
  const srcH = img.naturalHeight;
  if (srcW <= 0 || srcH <= 0) return { frame1: FALLBACK_SVG, frame2: null };

  const isTwoFrame = srcH > srcW;
  const frameH = isTwoFrame ? Math.floor(srcH / 2) : srcH;

  const frame1 = _extractFrame(img, srcW, frameH, 0);
  const frame2 = isTwoFrame ? _extractFrame(img, srcW, frameH, frameH) : null;

  return { frame1, frame2 };
}

function _extractFrame(img, w, h, yOffset) {
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");

  ctx.drawImage(img, 0, yOffset, w, h, 0, 0, w, h);

  try {
    const imageData = ctx.getImageData(0, 0, w, h);
    const data = imageData.data;
    const bgR = data[0], bgG = data[1], bgB = data[2];
    const TOLERANCE = 2;
    for (let i = 0; i < data.length; i += 4) {
      if (Math.abs(data[i]     - bgR) <= TOLERANCE &&
          Math.abs(data[i + 1] - bgG) <= TOLERANCE &&
          Math.abs(data[i + 2] - bgB) <= TOLERANCE) {
        data[i + 3] = 0;
      }
    }
    ctx.putImageData(imageData, 0, 0);
  } catch {
    // CORS or canvas security error -- return clipped but unprocessed
  }

  return canvas.toDataURL("image/png");
}

function _loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("Failed to load sprite"));
    img.src = url;
  });
}
