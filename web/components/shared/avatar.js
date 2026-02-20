// Avatar generation for humans and agents.
// Humans: circle. Agents: rounded-square with gold ring.

import { escapeHtml } from '../../core/utils.js';
import { AVATAR_COLORS } from '../../core/constants.js';

export function hashCode(str) {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash + str.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

export function avatarColor(name) {
  return AVATAR_COLORS[hashCode(name) % AVATAR_COLORS.length];
}

export function initialsFromName(name) {
  return name.split(' ').filter(Boolean).slice(0, 2).map(w => w[0]).join('').toUpperCase() || '?';
}

/** Generate SVG for agent avatar (rounded-square with bot face). */
export function generateBotSvg(name) {
  const color = avatarColor(name);
  const h = hashCode(name);
  const antennaStyle = h % 3;
  const eyeStyle = (h >> 2) % 3;
  const mouthStyle = (h >> 4) % 3;

  let antenna = '';
  if (antennaStyle === 0) {
    antenna = `<line x1="16" y1="6" x2="16" y2="2" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/><circle cx="16" cy="1.5" r="1.5" fill="#fff"/>`;
  } else if (antennaStyle === 1) {
    antenna = `<line x1="16" y1="6" x2="16" y2="2.5" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/><line x1="13.5" y1="2.5" x2="18.5" y2="2.5" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/>`;
  }

  let eyes = '';
  if (eyeStyle === 0) {
    eyes = `<circle cx="12" cy="16" r="2" fill="${color}"/><circle cx="20" cy="16" r="2" fill="${color}"/>`;
  } else if (eyeStyle === 1) {
    eyes = `<rect x="10" y="14" width="4" height="4" rx="0.5" fill="${color}"/><rect x="18" y="14" width="4" height="4" rx="0.5" fill="${color}"/>`;
  } else {
    eyes = `<rect x="10" y="15" width="4" height="2" rx="1" fill="${color}"/><rect x="18" y="15" width="4" height="2" rx="1" fill="${color}"/>`;
  }

  let mouth = '';
  if (mouthStyle === 0) {
    mouth = `<rect x="13" y="21" width="6" height="1.5" rx="0.75" fill="${color}"/>`;
  } else if (mouthStyle === 1) {
    mouth = `<path d="M13 21 Q16 24 19 21" stroke="${color}" stroke-width="1.5" fill="none" stroke-linecap="round"/>`;
  } else {
    mouth = `<rect x="13.5" y="20.5" width="5" height="2.5" rx="1.25" fill="${color}"/>`;
  }

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">${antenna}<rect x="3" y="6" width="26" height="24" rx="6" fill="${color}"/><rect x="7" y="10" width="18" height="16" rx="4" fill="#fff"/>${eyes}${mouth}</svg>`;
}

/** Generate SVG for human avatar (circle with initials). */
export function generateHumanSvg(name) {
  const color = avatarColor(name);
  const initials = initialsFromName(name);
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><circle cx="16" cy="16" r="16" fill="${color}"/><text x="16" y="16" text-anchor="middle" dominant-baseline="central" fill="#fff" font-family="Inter,sans-serif" font-weight="700" font-size="12">${escapeHtml(initials)}</text></svg>`;
}

/** Render avatar HTML - supports photo URL or generated SVG. */
export function renderAvatarHtml(name, pictureUrl, isAgent = false) {
  const shapeClass = isAgent ? 'avatar avatar-agent' : 'avatar avatar-human';
  if (pictureUrl) {
    return `<div class="${shapeClass}"><img src="${escapeHtml(pictureUrl)}" alt="" /></div>`;
  }
  const svg = isAgent ? generateBotSvg(name) : generateHumanSvg(name);
  return `<div class="${shapeClass}">${svg}</div>`;
}
