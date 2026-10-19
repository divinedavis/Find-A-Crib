#!/usr/bin/env python3
"""Building chat: a message sealed in a browser opens on an iPhone, and back.

The web chat (static/chat/chat-crypto.js, 2026-10-19) re-implements the
app's ChatCrypto (ios/FindACrib/Services/BuildingChat.swift). This runs the
REAL code of both: the Swift enum is cut out of the app source and compiled
with a stub Keychain, the JS module runs in Node's WebCrypto with the vendored
ChaCha20-Poly1305. Each side seals for the other's key; each must open it.

    python3 tests/chat_crypto_interop.py      # needs swift + node on PATH
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BBL = "3001497503"

SWIFT_MAIN = r'''
import Foundation
import CryptoKit
struct SecureStore { init(service: String) {}; func data(_ a: String) -> Data? { nil }; func set(_ d: Data, for a: String) {} }
%(chatcrypto)s

let args = CommandLine.arguments
func pub(_ b: String) -> Curve25519.KeyAgreement.PublicKey { try! .init(rawRepresentation: Data(base64Encoded: b)!) }
switch args[1] {
case "gen":
    let k = Curve25519.KeyAgreement.PrivateKey()
    print(k.rawRepresentation.base64EncodedString() + " " + ChatCrypto.publicKeyBase64(k))
case "reply":   // reply <myPrivB64> <myID> <webPubB64> <webID> <sealedJSONPath>
    let me = try! Curve25519.KeyAgreement.PrivateKey(rawRepresentation: Data(base64Encoded: args[2])!)
    let j = try! JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: args[6]))) as! [String: Any]
    let s = ChatCrypto.Sealed(salt: j["salt"] as! String, ciphertext: j["ciphertext"] as! String, keys: j["keys"] as! [String: String])
    let text = String(decoding: try! ChatCrypto.open(s, bbl: "%(bbl)s", myID: args[3], mine: me, senderKey: pub(args[4])), as: UTF8.self)
    let r = try! ChatCrypto.seal(Data("hello from the iPhone".utf8), bbl: "%(bbl)s", from: me, to: [args[5]: pub(args[4]), args[3]: me.publicKey])
    let out: [String: Any] = ["opened": text, "salt": r.salt, "ciphertext": r.ciphertext, "keys": r.keys]
    print(String(decoding: try! JSONSerialization.data(withJSONObject: out), as: UTF8.self))
default: exit(2)
}
'''

NODE_MAIN = r'''
const fs = require('fs'), vm = require('vm');
globalThis.window = globalThis; globalThis.btoa ??= s => Buffer.from(s, 'binary').toString('base64');
globalThis.atob ??= s => Buffer.from(s, 'base64').toString('binary');
for (const f of process.argv.slice(2, 4)) vm.runInThisContext(fs.readFileSync(f, 'utf8'));
const C = globalThis.FacChatCrypto, s = crypto.subtle, [mode, ...a] = process.argv.slice(4);
(async () => {
  if (mode === 'seal') {          // seal <phonePubB64> <phoneID> <webID>
    const kp = await s.generateKey({ name: 'X25519' }, true, ['deriveBits']);
    const pub = C.b64(new Uint8Array(await s.exportKey('raw', kp.publicKey)));
    const sealed = await C.seal(new TextEncoder().encode('hello from the web'), process.env.BBL, kp.privateKey, { [a[1]]: a[0], [a[2]]: pub });
    console.log(JSON.stringify({ jwk: await s.exportKey('jwk', kp.privateKey), pub, sealed }));
  } else {                        // open <jwkJSON> <webID> <phonePubB64> <sealedJSONPath>
    const priv = await s.importKey('jwk', JSON.parse(a[0]), { name: 'X25519' }, false, ['deriveBits']);
    const sealed = JSON.parse(fs.readFileSync(a[3], 'utf8'));
    console.log(new TextDecoder().decode(await C.open(sealed, process.env.BBL, a[1], priv, a[2])));
  }
})().catch(e => { console.error(e); process.exit(1); });
'''


def main():
    if not (shutil.which("swiftc") and shutil.which("node")):
        print("skip: needs swiftc and node"); return
    src = open(os.path.join(ROOT, "ios/FindACrib/Services/BuildingChat.swift")).read()
    m = re.search(r"^enum ChatCrypto \{.*?^\}\n", src, re.S | re.M)
    assert m, "ChatCrypto enum not found in BuildingChat.swift"
    with tempfile.TemporaryDirectory() as tmp:
        sw = os.path.join(tmp, "main.swift"); exe = os.path.join(tmp, "interop")
        open(sw, "w").write(SWIFT_MAIN % {"chatcrypto": m.group(0), "bbl": BBL})
        subprocess.run(["swiftc", "-O", sw, "-o", exe], check=True, env={**os.environ, "PATH": "/usr/bin:" + os.environ["PATH"]})
        js = os.path.join(tmp, "node.js"); open(js, "w").write(NODE_MAIN)
        libs = [os.path.join(ROOT, "static/chat/noble-chacha.js"), os.path.join(ROOT, "static/chat/chat-crypto.js")]
        env = {**os.environ, "BBL": BBL}
        phone_priv, phone_pub = subprocess.check_output([exe, "gen"], text=True).split()
        phone_id, web_id = "11111111-aaaa-bbbb-cccc-000000000001", "11111111-aaaa-bbbb-cccc-000000000002:0123456789abcdef"
        web = json.loads(subprocess.check_output(["node", js, *libs, "seal", phone_pub, phone_id, web_id], text=True, env=env))
        p1 = os.path.join(tmp, "web.json"); json.dump(web["sealed"], open(p1, "w"))
        reply = json.loads(subprocess.check_output([exe, "reply", phone_priv, phone_id, web["pub"], web_id, p1], text=True))
        assert reply["opened"] == "hello from the web", reply["opened"]
        p2 = os.path.join(tmp, "phone.json"); json.dump(reply, open(p2, "w"))
        back = subprocess.check_output(["node", js, *libs, "open", json.dumps(web["jwk"]), web_id, phone_pub, p2], text=True, env=env).strip()
        assert back == "hello from the iPhone", back
        # And a browser key must NOT open what wasn't wrapped for it.
        bad = subprocess.run(["node", js, *libs, "open", json.dumps(web["jwk"]), "someone-else", phone_pub, p2],
                             capture_output=True, text=True, env=env)
        assert bad.returncode != 0, "opened a message wrapped for someone else"
    print("chat crypto interop OK: web -> iPhone and iPhone -> web")


if __name__ == "__main__":
    sys.exit(main())
