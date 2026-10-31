/* shared helpers (no inline scripts: CSP-friendly) */
window.SHQ = {
  norm: function (s) {
    return (s || '').toLowerCase()
      .replace(/[\u064B-\u065F\u0670\u0640]/g, '')
      .replace(/[\u0623\u0625\u0622\u0671]/g, '\u0627')
      .replace(/\u0649/g, '\u064A').replace(/\u0629/g, '\u0647')
      .replace(/[\u0660-\u0669]/g, function (c) { return String(c.charCodeAt(0) - 0x660); })
      .replace(/\s+/g, ' ').trim();
  },
  esc: function (s) { return s.replace(/[&<>"]/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
};
