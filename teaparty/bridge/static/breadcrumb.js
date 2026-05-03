// Shared breadcrumb renderer for every static page under bridge/static/.
// The rightmost entry represents the current page and is non-linked; all
// prior entries are clickable links up the hierarchy.
function breadcrumbBar(parts) {
  if (!parts || parts.length === 0) return '';
  return '<div class="breadcrumb-bar">' + parts.map(function(p, i) {
    var sep = i > 0 ? ' <span class="sep">/</span> ' : '';
    if (p.href) {
      return sep + '<a href="' + p.href + '">' + p.label + '</a>';
    }
    if (p.onClick) {
      return sep + '<a onclick="' + p.onClick + '" style="cursor:pointer">' + p.label + '</a>';
    }
    return sep + '<span class="current">' + p.label + '</span>';
  }).join('') + '</div>';
}

function setBreadcrumb(slotId, parts) {
  var slot = document.getElementById(slotId);
  if (slot) slot.innerHTML = breadcrumbBar(parts);
}
