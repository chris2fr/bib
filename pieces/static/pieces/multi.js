// Complétion pour les champs à valeurs multiples (data-multi="keywords") : on tape, la suite est proposée.
// Tab / Entrée acceptent la proposition surlignée, ↑ ↓ changent de proposition, Échap ferme. Sans JavaScript, le champ reste un texte libre.
(function () {
  var data = document.getElementById('multi-values');
  if (!data) return;
  var all = JSON.parse(data.textContent);
  var SEP = /[;,]/;
  function fold(s) { return s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase(); }

  document.querySelectorAll('[data-multi]').forEach(function (input) {
    var values = all[input.dataset.multi] || [];
    var wrap = document.createElement('span');
    wrap.className = 'multiwrap';
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    var box = document.createElement('ul');
    box.className = 'suggest';
    box.hidden = true;
    box.setAttribute('role', 'listbox');
    wrap.appendChild(box);
    var shown = [], active = 0;

    // portion de texte en cours de frappe : entre le dernier séparateur avant le curseur et le prochain séparateur
    function current() {
      var v = input.value, pos = input.selectionStart;
      var start = Math.max(v.lastIndexOf(',', pos - 1), v.lastIndexOf(';', pos - 1)) + 1;
      var next = v.slice(pos).search(SEP);
      var end = next < 0 ? v.length : pos + next;
      while (start < end && /\s/.test(v.charAt(start))) start++;
      return { start: start, end: end, typed: v.slice(start, pos).trim() };
    }
    function close() { box.hidden = true; shown = []; }
    function render() {
      box.innerHTML = '';
      shown.forEach(function (val, i) {
        var li = document.createElement('li');
        li.textContent = val;
        li.setAttribute('role', 'option');
        if (i === active) li.className = 'active';
        li.addEventListener('mousedown', function (e) { e.preventDefault(); accept(val); });
        box.appendChild(li);
      });
      box.hidden = !shown.length;
    }
    function suggest() {
      var cur = current(), t = fold(cur.typed);
      if (!t) return close();
      var v = input.value;
      var have = (v.slice(0, cur.start) + ',' + v.slice(cur.end)).split(SEP).map(function (x) { return fold(x.trim()); });
      var starts = [], inside = [];
      values.forEach(function (val) {
        var f = fold(val);
        if (have.indexOf(f) >= 0 && f !== t) return;
        if (f === t) return;
        (f.indexOf(t) === 0 ? starts : f.indexOf(t) > 0 ? inside : []).push(val);
      });
      shown = starts.concat(inside).slice(0, 8);
      active = 0;
      render();
    }
    function accept(val) {
      var cur = current(), v = input.value;
      var spaced = /[;,]\s/.test(v);
      var tail = v.slice(cur.end), sep = tail.charAt(0) === ',' || tail.charAt(0) === ';' ? '' : (spaced ? ', ' : ',');
      input.value = v.slice(0, cur.start) + val + sep + tail;
      var caret = cur.start + val.length + sep.length;
      input.setSelectionRange(caret, caret);
      close();
      input.focus();
    }
    input.addEventListener('input', suggest);
    input.addEventListener('click', close);
    input.addEventListener('blur', close);
    input.addEventListener('keydown', function (e) {
      if (box.hidden) return;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        active = (active + (e.key === 'ArrowDown' ? 1 : shown.length - 1)) % shown.length;
        render();
      } else if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault();
        accept(shown[active]);
      } else if (e.key === 'Escape') {
        close();
      } else return;
      e.preventDefault();
    });
  });
})();
