/* Building chat encryption for findacrib.com (owner, 2026-10-19: chat on the
 * web too). The same scheme as the iPhone app's ChatCrypto
 * (ios/FindACrib/Services/BuildingChat.swift), byte for byte, so a message
 * sealed in Safari opens on a phone and the other way round:
 *
 *   wrap key  = HKDF-SHA256(X25519(mine, theirs), salt, "fac-chat-v1|<bbl>", 32)
 *   body      = ChaCha20-Poly1305(message key)   as nonce(12) | ciphertext | tag(16)
 *   keys[id]  = ChaCha20-Poly1305(wrap key)(message key), same layout
 *
 * X25519 and HKDF come from WebCrypto; ChaCha20-Poly1305 from the vendored
 * @noble/ciphers (static/chat/noble-chacha.js, window.facChaCha).
 *
 * This browser's key never leaves it: a non-extractable X25519 CryptoKey kept
 * in IndexedDB beside a random device id. Its public half is published in
 * chat_devices; senders wrap for "<account>:<device>" (db/0067).
 */
(function (root) {
  'use strict';
  var subtle = root.crypto && root.crypto.subtle;
  var enc = new TextEncoder();

  function b64(bytes) { var s = ''; for (var i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]); return btoa(s); }
  function unb64(str) { var s = atob(str), out = new Uint8Array(s.length); for (var i = 0; i < s.length; i++) out[i] = s.charCodeAt(i); return out; }
  function random(n) { var a = new Uint8Array(n); root.crypto.getRandomValues(a); return a; }
  function hex(bytes) { return Array.prototype.map.call(bytes, function (b) { return ('0' + b.toString(16)).slice(-2); }).join(''); }

  function chachaSeal(key, plain) {
    var nonce = random(12), ct = root.facChaCha(key, nonce).encrypt(plain);
    var out = new Uint8Array(12 + ct.length); out.set(nonce); out.set(ct, 12); return out;
  }
  function chachaOpen(key, combined) {
    if (combined.length < 28) throw new Error('short box');
    return root.facChaCha(key, combined.subarray(0, 12)).decrypt(combined.subarray(12));
  }

  function importPublic(pubB64) {
    var raw = unb64(pubB64);
    if (raw.length !== 32) return Promise.reject(new Error('bad key'));
    return subtle.importKey('raw', raw, { name: 'X25519' }, true, []);
  }

  function wrappingKey(myPrivate, theirPublic, salt, bbl) {
    return subtle.deriveBits({ name: 'X25519', public: theirPublic }, myPrivate, 256)
      .then(function (shared) { return subtle.importKey('raw', shared, 'HKDF', false, ['deriveBits']); })
      .then(function (ikm) {
        return subtle.deriveBits({ name: 'HKDF', hash: 'SHA-256', salt: salt, info: enc.encode('fac-chat-v1|' + bbl) }, ikm, 256);
      })
      .then(function (bits) { return new Uint8Array(bits); });
  }

  /* members: { id: publicKeyBase64 } — "<uid>" for a phone, "<uid>:<device>" for a browser. */
  function seal(plain, bbl, myPrivate, members) {
    var messageKey = random(32), salt = random(16);
    var body = chachaSeal(messageKey, plain), keys = {};
    var ids = Object.keys(members);
    return Promise.all(ids.map(function (id) {
      return importPublic(members[id])
        .then(function (pub) { return wrappingKey(myPrivate, pub, salt, bbl); })
        .then(function (w) { keys[id] = b64(chachaSeal(w, messageKey)); })
        .catch(function () { /* one bad published key must not stop the message */ });
    })).then(function () { return { salt: b64(salt), ciphertext: b64(body), keys: keys }; });
  }

  function open(sealed, bbl, myId, myPrivate, senderPublicB64) {
    var wrapped = sealed.keys && sealed.keys[myId];
    if (!wrapped) return Promise.reject(new Error('not for this device'));
    return importPublic(senderPublicB64)
      .then(function (pub) { return wrappingKey(myPrivate, pub, unb64(sealed.salt), bbl); })
      .then(function (w) { return chachaOpen(chachaOpen(w, unb64(wrapped)), unb64(sealed.ciphertext)); });
  }

  /* ---- this browser's identity (IndexedDB) ---- */
  var DB = 'fac-chat', STORE = 'keys', ID = 'identity-v1';
  function idb(mode, fn) {
    return new Promise(function (resolve, reject) {
      var req = root.indexedDB.open(DB, 1);
      req.onupgradeneeded = function () { req.result.createObjectStore(STORE); };
      req.onerror = function () { reject(req.error); };
      req.onsuccess = function () {
        var tx = req.result.transaction(STORE, mode), r = fn(tx.objectStore(STORE));
        tx.oncomplete = function () { resolve(r && r.result); req.result.close(); };
        tx.onerror = function () { reject(tx.error); };
      };
    });
  }
  function identity() {
    return idb('readonly', function (s) { return s.get(ID); }).then(function (found) {
      if (found && found.privateKey && found.publicKey && found.deviceId) return found;
      return subtle.generateKey({ name: 'X25519' }, false, ['deriveBits']).then(function (kp) {
        return subtle.exportKey('raw', kp.publicKey).then(function (raw) {
          var me = { deviceId: hex(random(8)), privateKey: kp.privateKey, publicKey: b64(new Uint8Array(raw)) };
          return idb('readwrite', function (s) { return s.put(me, ID); }).then(function () { return me; });
        });
      });
    });
  }

  /* Can this browser do it? X25519 in WebCrypto: Safari 17, Chrome 133, Firefox 130. */
  function supported() {
    if (!subtle || !root.indexedDB || !root.facChaCha) return Promise.resolve(false);
    return subtle.generateKey({ name: 'X25519' }, false, ['deriveBits']).then(function () { return true; }, function () { return false; });
  }

  root.FacChatCrypto = { seal: seal, open: open, identity: identity, supported: supported,
                         b64: b64, unb64: unb64, _wrappingKey: wrappingKey };
})(typeof window !== 'undefined' ? window : globalThis);
