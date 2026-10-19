/* Building chat on findacrib.com (owner, 2026-10-19: "build chat on the web
 * too", with typing bubbles). The web twin of the app's BuildingChat +
 * BuildingChatView: same tables (db/0063, db/0067), same encryption
 * (chat-crypto.js), same rules (terms before joining, report, block, a
 * client-side filter because the server only sees ciphertext).
 *
 *   FacBuildingChat.open({ bbl, address, client })   // client = supabase-js
 *
 * Everything people typed is put on the page with textContent, never HTML.
 */
(function () {
  'use strict';
  var C = window.FacChatCrypto;
  var TYPING_EVERY = 2500, TYPING_SHOWN = 5000, RUN_GAP = 5 * 60 * 1000;
  var BLOCKED_WORDS = ['nigger', 'nigga', 'faggot', 'fag', 'kike', 'spic', 'chink', 'tranny', 'retard',
                       'kill yourself', 'kys', 'i will kill you', "i'll kill you"];   // = ChatFilter in BuildingChat.swift
  var REPORT_REASONS = ['Harassment or hate', 'Threat or violence', 'Spam or scam', 'Something else'];

  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    if (attrs) for (var k in attrs) {
      if (k === 'text') n.textContent = attrs[k];
      else if (k === 'on') for (var e in attrs.on) n.addEventListener(e, attrs.on[e]);
      else if (attrs[k] !== null && attrs[k] !== undefined && attrs[k] !== false) n.setAttribute(k, attrs[k] === true ? '' : attrs[k]);
    }
    (kids || []).forEach(function (c) { if (c) n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  }
  function track(name, props) { try { window.facTrack && window.facTrack(name, props); } catch (e) {} }

  function blocks(text) {
    var t = ' ' + text.toLowerCase().replace(/[^a-z' ]/g, ' ') + ' ';
    return BLOCKED_WORDS.some(function (w) { return t.indexOf(' ' + w + ' ') >= 0; });
  }

  /* ---- layout rules (exported for tests) ---- */
  function sameDay(a, b) { return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate(); }
  function dayLabel(d, now) {
    now = now || new Date();
    if (sameDay(d, now)) return 'Today';
    var y = new Date(now); y.setDate(y.getDate() - 1);
    if (sameDay(d, y)) return 'Yesterday';
    var o = d.getFullYear() === now.getFullYear() ? { weekday: 'short', month: 'short', day: 'numeric' } : { month: 'short', day: 'numeric', year: 'numeric' };
    return d.toLocaleDateString('en-US', o);
  }
  function runs(ms, now) {
    var out = [], cur = null, lastDay = null;
    ms.forEach(function (m) {
      var day = m.at.toDateString(), label = null;
      if (day !== lastDay) { label = dayLabel(m.at, now); lastDay = day; cur = null; }
      if (!cur || cur.sender !== m.sender || m.at - cur.messages[cur.messages.length - 1].at > RUN_GAP) {
        cur = { sender: m.sender, mine: m.mine, messages: [], dayLabel: label }; out.push(cur);
      }
      cur.messages.push(m);
    });
    return out;
  }
  function initials(name) {
    var w = (name || '').split(/[^\p{L}\p{N}]+/u).filter(Boolean).slice(0, 2);
    return w.map(function (x) { return x[0]; }).join('').toUpperCase() || '•';
  }
  function typingLine(names) {
    if (!names.length) return '';
    if (names.length === 1) return names[0] + ' is typing…';
    if (names.length === 2) return names[0] + ' and ' + names[1] + ' are typing…';
    return names.length + ' neighbors are typing…';
  }
  function clock(d) { return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }); }

  /* ---- the chat ---- */
  function open(opts) {
    var sb = opts.client, bbl = opts.bbl, address = opts.address || 'your building';
    var state = { me: null, myKey: null, ident: null, keys: {}, messages: [], blocked: {}, joined: false,
                  members: 0, typers: {}, lastTyping: 0, detail: null, ch: null, typingCh: null, timer: null };

    var root = el('div', { class: 'fc-chat', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Building chat', 'data-testid': 'chat-sheet' });
    var back = el('div', { class: 'fc-chat-backdrop' }, [root]);
    var closeBtn = el('button', { class: 'fc-chat-x', type: 'button', text: 'Close', on: { click: close } });
    var leaveBtn = el('button', { class: 'fc-chat-x', type: 'button', text: 'Leave', hidden: true, 'data-testid': 'chat-leave', on: { click: leave } });
    root.appendChild(el('div', { class: 'fc-chat-head' }, [closeBtn, el('h2', { text: 'Building chat · ' + address }), leaveBtn]));
    var body = el('div', { class: 'fc-chat-body' });
    root.appendChild(body);
    document.body.appendChild(back);
    var prevOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden';
    back.addEventListener('click', function (e) { if (e.target === back) close(); });
    document.addEventListener('keydown', onKey);
    function onKey(e) { if (e.key === 'Escape') { if (state.detail) showDetail(null); else close(); } }

    function close() {
      stopLive(); document.removeEventListener('keydown', onKey);
      document.body.style.overflow = prevOverflow; back.remove();
    }
    function setBody(node) { body.textContent = ''; body.appendChild(node); }
    function lockLine() { return el('span', { class: 'fc-lock', text: '🔒 End-to-end encrypted' }); }
    function fail(text) { setBody(el('div', { class: 'fc-card' }, [el('p', { class: 'err', text: text })])); }

    function start() {
      setBody(el('div', { class: 'fc-card' }, [el('p', { text: 'Loading…' })]));
      C.supported().then(function (ok) {
        if (!ok) return fail('This browser can’t do encrypted chat. Update it, or use the Find A Crib iPhone app.');
        return sb.auth.getSession().then(function (r) {
          var sess = r && r.data && r.data.session;
          if (!sess) return signedOut();
          state.me = sess.user.id.toLowerCase();
          try { sb.realtime.setAuth(sess.access_token); } catch (e) {}
          return C.identity().then(function (id) {
            state.ident = id; state.myKey = state.me + ':' + id.deviceId;
            return sb.from('chat_members').select('user_id').eq('bbl', bbl).eq('user_id', state.me);
          }).then(function (r) {
            if (r.error) throw r.error;
            state.joined = r.data.length > 0;
            if (!state.joined) return joinCard();
            return publishDevice().then(refresh).then(function () { room(); goLive(); });
          });
        });
      }).catch(function () { fail('Couldn’t reach the chat. Close it and try again.'); });
    }

    function signedOut() {
      setBody(el('div', { class: 'fc-card' }, [
        lockLine(),
        el('h3', { text: 'Talk with the people in ' + address }),
        el('p', { text: 'Sign in to join your building’s chat. Messages are end-to-end encrypted: only the people in the chat can read them.' }),
        el('a', { class: 'btn', href: '/?auth=signup&next=' + encodeURIComponent('/casa/?bbl=' + bbl + '&chat=1'), 'data-testid': 'chat-signin', text: 'Sign in to chat' })
      ]));
    }

    function joinCard() {
      var name = el('input', { type: 'text', maxlength: '40', placeholder: 'e.g. Maria, 4B', 'data-testid': 'chat-name', autocomplete: 'nickname' });
      try { name.value = localStorage.getItem('fac.chat.name') || ''; } catch (e) {}
      var agree = el('input', { type: 'checkbox', 'data-testid': 'chat-terms' });
      var join = el('button', { class: 'btn', type: 'button', text: 'Join the chat', 'data-testid': 'chat-join', disabled: true });
      var err = el('p', { class: 'err', hidden: true });
      function check() { join.disabled = !(agree.checked && name.value.trim()); }
      name.addEventListener('input', check); agree.addEventListener('change', check); check();
      join.addEventListener('click', function () {
        join.disabled = true;
        try { localStorage.setItem('fac.chat.name', name.value.trim()); } catch (e) {}
        publishDevice().then(function () {
          return sb.from('chat_members').upsert({ bbl: bbl, user_id: state.me, agreed_terms_at: new Date().toISOString() },
                                                 { onConflict: 'bbl,user_id', ignoreDuplicates: true });
        }).then(function (r) {
          if (r.error) throw r.error;
          state.joined = true; track('chat_join', { bbl: bbl, web: true });
          return refresh().then(function () { room(); goLive(); });
        }).catch(function () { err.textContent = 'Couldn’t join the chat. Try again.'; err.hidden = false; check(); });
      });
      setBody(el('div', { class: 'fc-card' }, [
        lockLine(),
        el('h3', { text: 'Talk with the people in ' + address }),
        el('p', { text: 'Messages are end-to-end encrypted: only the people in this chat can read them — not Find A Crib, not your landlord. You’ll see messages sent after you join on this browser.' }),
        el('label', { class: 'fc-field', text: 'Your name in the chat' }), name,
        el('label', { class: 'fc-terms' }, [agree, el('span', { text: 'I’ll be respectful. No harassment, hate, threats, spam or sharing people’s private details. Find A Crib removes anyone who breaks these rules.' })]),
        join, err
      ]));
    }

    function publishDevice() {
      return sb.from('chat_devices').upsert({ user_id: state.me, device_id: state.ident.deviceId, public_key: state.ident.publicKey,
                                              updated_at: new Date().toISOString() }, { onConflict: 'user_id,device_id' })
        .then(function (r) { if (r.error) throw r.error; });
    }

    /* Members' phone + browser keys, blocks, then the last 100 messages. */
    function refresh() {
      return sb.from('chat_members').select('user_id').eq('bbl', bbl).then(function (r) {
        if (r.error) throw r.error;
        var ids = r.data.map(function (x) { return x.user_id; });
        state.members = ids.length;
        if (!ids.length) return;
        return Promise.all([
          sb.from('chat_keys').select('user_id,public_key').in('user_id', ids),
          sb.from('chat_devices').select('user_id,device_id,public_key').in('user_id', ids),
          sb.from('chat_blocks').select('blocked')
        ]).then(function (rs) {
          var k = {};
          (rs[0].data || []).forEach(function (x) { k[x.user_id.toLowerCase()] = x.public_key; });
          (rs[1].data || []).forEach(function (x) { k[x.user_id.toLowerCase() + ':' + x.device_id] = x.public_key; });
          state.keys = k; state.blocked = {};
          (rs[2].data || []).forEach(function (x) { state.blocked[x.blocked.toLowerCase()] = true; });
        });
      }).then(function () {
        return sb.from('chat_messages').select('*').eq('bbl', bbl).order('id', { ascending: false }).limit(100);
      }).then(function (r) {
        if (r.error) throw r.error;
        return Promise.all(r.data.reverse().map(decode)).then(function (ms) { state.messages = ms; });
      });
    }

    function senderKeyId(row) { var s = row.sender.toLowerCase(); return row.sender_device ? s + ':' + row.sender_device : s; }

    function decode(row) {
      var sender = row.sender.toLowerCase();
      var m = { id: row.id, sender: sender, name: 'Neighbor', text: null, at: new Date(row.created_at), mine: sender === state.me, fromWeb: !!row.sender_device };
      var pub = state.keys[senderKeyId(row)];
      if (!pub) return Promise.resolve(m);
      return C.open({ salt: row.salt, ciphertext: row.ciphertext, keys: row.keys }, bbl, state.myKey, state.ident.privateKey, pub)
        .then(function (bytes) {
          var p = JSON.parse(new TextDecoder().decode(bytes));
          if (typeof p.t === 'string') m.text = p.t;
          if (typeof p.n === 'string' && p.n) m.name = p.n.slice(0, 40);
          return m;
        }, function () { return m; });
    }

    /* ---- the room ---- */
    var scroll, col, typingBox, composer, input, sendBtn, errLine, detail, barCount;
    function room() {
      leaveBtn.hidden = false;
      barCount = el('span');
      scroll = el('div', { class: 'fc-scroll' });
      col = el('div', { class: 'fc-col' });
      scroll.appendChild(col);
      input = el('textarea', { rows: '1', maxlength: '2000', placeholder: 'Message your building', 'aria-label': 'Message', 'data-testid': 'chat-input' });
      sendBtn = el('button', { class: 'fc-send', type: 'button', 'aria-label': 'Send', 'data-testid': 'chat-send', disabled: true, text: '↑' });
      errLine = el('div', { class: 'fc-err', hidden: true });
      composer = el('div', { class: 'fc-compose' }, [input, sendBtn]);
      detail = el('aside', { class: 'fc-detail', hidden: true, 'aria-label': 'Message details', 'data-testid': 'chat-detail' });
      var r = el('div', { class: 'fc-room' }, [
        el('div', { class: 'fc-chat-bar' }, [lockLine(), barCount]), scroll, errLine, composer]);
      setBody(el('div', { class: 'fc-chat-body', style: 'flex:1;min-height:0;position:relative' }, [r, detail]));
      input.addEventListener('input', function () {
        input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 140) + 'px';
        sendBtn.disabled = !input.value.trim();
        typed(input.value);
      });
      input.addEventListener('keydown', function (e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } });
      sendBtn.addEventListener('click', send);
      render(true);
      input.focus();
    }

    function visible() { return state.messages.filter(function (m) { return !state.blocked[m.sender]; }); }

    function render(toBottom) {
      if (!col) return;
      var nearBottom = toBottom || scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 80;
      barCount.textContent = state.members === 1 ? 'Just you so far' : state.members + ' neighbors';
      col.textContent = '';
      var ms = visible();
      if (!ms.length) col.appendChild(el('p', { class: 'fc-empty', 'data-testid': 'chat-empty', text: 'No messages yet. Say hello to your neighbors.' }));
      runs(ms).forEach(function (run) {
        if (run.dayLabel) col.appendChild(el('div', { class: 'fc-day', 'data-testid': 'chat-day', role: 'separator', text: run.dayLabel }));
        var first = run.messages[0], who = first.mine ? 'You' : first.name;
        var box = el('div', { class: 'fc-run' + (first.mine ? ' mine' : '') }, [
          el('div', { class: 'fc-run-head' }, [
            el('span', { class: 'fc-av', 'aria-hidden': 'true', text: initials(who) }),
            el('span', { class: 'fc-name', text: who }),
            el('time', { class: 'fc-time', 'data-testid': 'chat-time', datetime: first.at.toISOString(), text: clock(first.at) })
          ])
        ]);
        run.messages.forEach(function (m) {
          var b = el('button', { type: 'button', class: 'fc-msg' + (m.text === null ? ' locked' : ''), 'data-testid': 'chat-message',
                                 'aria-current': state.detail && state.detail.id === m.id ? 'true' : null,
                                 text: m.text === null ? 'Sent before this browser joined, so it can’t be read here' : m.text });
          b.addEventListener('click', function () { showDetail(m); });
          box.appendChild(b);
        });
        col.appendChild(box);
      });
      typingBox = null;
      var names = typingNames();
      if (names.length) {
        typingBox = el('div', { class: 'fc-typing', 'data-testid': 'chat-typing' }, [
          el('span', { class: 'fc-dots', 'aria-hidden': 'true' }, [el('i'), el('i'), el('i')]),
          el('div', { class: 'fc-typing-line', text: typingLine(names) })
        ]);
        col.appendChild(typingBox);
      }
      if (nearBottom) scroll.scrollTop = scroll.scrollHeight;
    }

    /* REVEAL: the detail is a sheet on narrow chats and a side panel on wide
       ones — chat.css decides by the chat's own width (@container). */
    function showDetail(m) {
      state.detail = m;
      detail.textContent = '';
      detail.appendChild(el('p', { class: 'fc-detail-hint', text: 'Tap a message to see when it was sent, or to report it.' }));
      if (!m) { detail.hidden = true; render(); return; }
      detail.appendChild(el('button', { class: 'fc-chat-x fc-detail-close', type: 'button', text: 'Done', on: { click: function () { showDetail(null); } } }));
      detail.appendChild(el('h3', { text: m.mine ? 'You' : m.name }));
      detail.appendChild(el('p', { class: 'fc-text', text: m.text === null
        ? 'This browser joined after the message was sent, or it was sent to an older key. Only devices in the chat at the time can read it.' : m.text }));
      detail.appendChild(el('dl', null, [
        el('dt', { text: 'Sent' }), el('dd', { text: m.at.toLocaleString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' }) }),
        el('dt', { text: 'From' }), el('dd', { text: m.fromWeb ? 'findacrib.com' : 'iPhone app' }),
        el('dt', { text: 'Privacy' }), el('dd', { text: 'End-to-end encrypted' })
      ]));
      var acts = el('div', { class: 'fc-actions' });
      if (m.text !== null && navigator.clipboard) acts.appendChild(el('button', { type: 'button', text: 'Copy', on: { click: function () { navigator.clipboard.writeText(m.text); } } }));
      if (!m.mine) {
        acts.appendChild(el('button', { type: 'button', 'data-testid': 'chat-detail-report', text: 'Report', on: { click: function () { reportFlow(m); } } }));
        acts.appendChild(el('button', { type: 'button', class: 'danger', text: 'Block ' + m.name, on: { click: function () { block(m); } } }));
      }
      detail.appendChild(acts);
      detail.hidden = false;
      render();
    }

    function reportFlow(m) {
      var acts = detail.querySelector('.fc-actions'); acts.textContent = '';
      acts.appendChild(el('p', { class: 'muted', style: 'width:100%;margin:0', text: 'This sends the message’s text to Find A Crib to review. Messages are otherwise unreadable to us.' }));
      REPORT_REASONS.forEach(function (reason) {
        acts.appendChild(el('button', { type: 'button', text: reason, on: { click: function () {
          sb.from('chat_reports').insert({ message_id: m.id, bbl: bbl, sender: m.sender, plaintext: m.text, reason: reason }).then(function (r) {
            acts.textContent = '';
            acts.appendChild(el('p', { class: 'muted', style: 'margin:0', text: r.error ? 'Couldn’t send the report. Try again.' : 'Thanks — we’ll review it within 24 hours.' }));
          });
        } } }));
      });
    }

    function block(m) {
      sb.from('chat_blocks').insert({ blocked: m.sender }).then(function () { state.blocked[m.sender] = true; showDetail(null); });
    }

    function leave() {
      if (!confirm('Leave the chat for ' + address + '?')) return;
      sb.from('chat_members').delete().eq('bbl', bbl).eq('user_id', state.me).then(function () { stopLive(); close(); });
    }

    function send() {
      var t = input.value.trim(), name = '';
      if (!t || t.length > 2000) return;
      try { name = (localStorage.getItem('fac.chat.name') || '').slice(0, 40); } catch (e) {}
      if (blocks(t)) return showErr('That message breaks the chat rules and wasn’t sent.');
      sendBtn.disabled = true;
      refresh().then(function () {
        var payload = new TextEncoder().encode(JSON.stringify({ t: t, n: name }));
        return C.seal(payload, bbl, state.ident.privateKey, state.keys);
      }).then(function (s) {
        return sb.from('chat_messages').insert({ bbl: bbl, salt: s.salt, ciphertext: s.ciphertext, keys: s.keys, sender_device: state.ident.deviceId });
      }).then(function (r) {
        if (r.error) throw r.error;
        input.value = ''; input.style.height = 'auto'; errLine.hidden = true;
        typed('');
        track('chat_send', { bbl: bbl, members: Object.keys(state.keys).length, web: true });
        render(true);
      }).catch(function () { showErr('Couldn’t send. Check your connection and try again.'); })
        .then(function () { sendBtn.disabled = !input.value.trim(); });
    }
    function showErr(t) { errLine.textContent = t; errLine.hidden = false; }

    /* ---- live: new messages + typing bubbles ---- */
    function goLive() {
      state.ch = sb.channel('chat-' + bbl)
        .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'chat_messages', filter: 'bbl=eq.' + bbl }, function (p) {
          var row = p.new;
          if (!row || state.messages.some(function (m) { return m.id === row.id; })) return;
          var ready = state.keys[senderKeyId(row)] ? Promise.resolve() : refresh();
          ready.then(function () { return state.messages.some(function (m) { return m.id === row.id; }) ? null : decode(row); })
            .then(function (m) { if (m) state.messages.push(m); delete state.typers[row.sender.toLowerCase()]; render(); });
        })
        .subscribe();
      state.typingCh = sb.channel('chat-typing:' + bbl, { config: { private: true, broadcast: { self: false } } })
        .on('broadcast', { event: 'typing' }, function (msg) {
          var p = msg && msg.payload || {}, who = typeof p.u === 'string' ? p.u.toLowerCase() : null;
          if (!who || who === state.me || state.blocked[who]) return;
          if (p.stop) delete state.typers[who]; else state.typers[who] = Date.now();
          render();
          clearTimeout(state.timer);
          state.timer = setTimeout(render, TYPING_SHOWN + 50);
        })
        .subscribe();
    }
    function stopLive() {
      clearTimeout(state.timer);
      if (state.ch) sb.removeChannel(state.ch);
      if (state.typingCh) sb.removeChannel(state.typingCh);
      state.ch = state.typingCh = null;
    }
    function typingNames() {
      var now = Date.now();
      return Object.keys(state.typers).filter(function (u) { return now - state.typers[u] < TYPING_SHOWN; })
        .sort(function (a, b) { return state.typers[a] - state.typers[b]; })
        .map(function (u) {
          for (var i = state.messages.length - 1; i >= 0; i--) {
            var m = state.messages[i]; if (m.sender === u && m.text !== null) return m.name;
          }
          return 'A neighbor';
        });
    }
    function typed(draft) {
      if (!state.typingCh) return;
      if (!draft.trim()) {
        if (!state.lastTyping) return;
        state.lastTyping = 0;
        state.typingCh.send({ type: 'broadcast', event: 'typing', payload: { u: state.me, stop: true } });
        return;
      }
      if (Date.now() - state.lastTyping < TYPING_EVERY) return;
      state.lastTyping = Date.now();
      state.typingCh.send({ type: 'broadcast', event: 'typing', payload: { u: state.me } });
    }

    start();
    return { close: close };
  }

  window.FacBuildingChat = { open: open, _runs: runs, _dayLabel: dayLabel, _initials: initials, _typingLine: typingLine, _blocks: blocks };
})();
