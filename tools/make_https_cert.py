"""Make the certificate the owner's stack serves HTTPS with on the home network (docs/pages.md, "HTTPS").

    python3 tools/make_https_cert.py --host <this computer's IPv4 address> [--host <a name for it>]
    python3 tools/make_https_cert.py --host ... --force     # again: expired, or the address changed

Browsers keep Structr's sign-in only over HTTPS (or at localhost), and Structr serves HTTPS itself given
a keystore, so nothing new is installed. This writes to private/https/, which git ignores:
    ca.crt         the authority's certificate, to trust on each device; not a secret
    keystore.p12   the server's key and certificate
    structr.env    the keystore's password, as the setting Structr reads
tools/owner_stack.sh up serves HTTPS on port 8443 while keystore.p12 is there.

A device that trusts an authority believes whatever it signs. So this one is limited to the hosts given
(critical name constraints), and its key is deleted once it has signed the one certificate: there is
nothing to steal that could sign another. The cost: a new certificate is a new authority, to trust again
on each device. Needs openssl; needs no Structr and reads no .env.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "private" / "https"
CA_DAYS = 825       # Apple accepts no server certificate valid for longer
SERVER_DAYS = 820   # inside the authority's
NAME = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*")
NO_NAMES = "none.invalid"     # constraints apply by kind: with no DNS entry every DNS name would be allowed


class CertError(RuntimeError):
    pass


def parse_hosts(given: list[str]) -> tuple[list[str], list[str]]:
    """(IPv4 addresses, DNS names), checked: both end up inside an openssl configuration."""
    addresses, names = [], []
    for host in given:
        host = host.strip().lower()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if not NAME.fullmatch(host) or re.fullmatch(r"[0-9.]+", host):
                raise CertError(f"{host!r} is neither an IPv4 address nor a host name") from None
            if host == "localhost":
                # Structr sends HSTS, which would turn http://localhost:8085 into https on that same port
                raise CertError("localhost needs no certificate: browsers keep a sign-in there over HTTP")
            names.append(host)
            continue
        if address.version != 4 or address.is_loopback or address.is_unspecified:
            raise CertError(f"{host!r}: give the IPv4 address other devices open")
        addresses.append(str(address))
    return addresses, names


def ca_config(addresses: list[str], names: list[str]) -> str:
    permitted = [f"permitted;IP:{a}/255.255.255.255" for a in addresses]
    if not addresses:
        permitted.append("permitted;IP:0.0.0.0/255.255.255.255")    # the same trap, for addresses
    permitted += [f"permitted;DNS:{n}" for n in names or [NO_NAMES]]
    return ("[req]\ndistinguished_name=dn\nx509_extensions=ext\nprompt=no\n"
            "[dn]\nCN=Meal planner home authority\n"
            "[ext]\nbasicConstraints=critical,CA:TRUE,pathlen:0\nkeyUsage=critical,keyCertSign,cRLSign\n"
            "subjectKeyIdentifier=hash\n"
            f"nameConstraints=critical,{','.join(permitted)}\n")


def server_extensions(addresses: list[str], names: list[str]) -> str:
    san = [f"IP:{a}" for a in addresses] + [f"DNS:{n}" for n in names]
    return ("basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n"
            "extendedKeyUsage=serverAuth\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid\n"
            f"subjectAltName={','.join(san)}\n")


def openssl(work: Path, *args: str, env: dict | None = None) -> str:
    done = subprocess.run(["openssl", *args], cwd=work, env={**os.environ, **(env or {})}, capture_output=True, text=True)
    if done.returncode != 0:
        raise CertError(f"openssl {args[0]} failed: {done.stderr.strip()[-400:]}")
    return done.stdout


def make_authority(work: Path, addresses: list[str], names: list[str]) -> None:
    (work / "ca.cnf").write_text(ca_config(addresses, names))
    openssl(work, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", str(CA_DAYS),
            "-config", "ca.cnf", "-keyout", "ca.key", "-out", "ca.crt")


def sign_server(work: Path, addresses: list[str], names: list[str]) -> None:
    (work / "server.ext").write_text(server_extensions(addresses, names))
    openssl(work, "req", "-new", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=Meal planner",
            "-keyout", "server.key", "-out", "server.csr")
    openssl(work, "x509", "-req", "-sha256", "-days", str(SERVER_DAYS), "-in", "server.csr", "-CA", "ca.crt",
            "-CAkey", "ca.key", "-set_serial", f"0x{secrets.randbits(120) | 1:x}", "-extfile", "server.ext",
            "-out", "server.crt")


def make(out: Path, hosts: list[str], force: bool = False) -> str:
    """Write the three files. Returns the authority's SHA-256 fingerprint, to compare on each device."""
    addresses, names = parse_hosts(hosts)
    if (out / "keystore.p12").exists() and not force:
        raise CertError(f"{out} already holds a certificate; --force replaces it, and every device must trust the new one")
    out.mkdir(parents=True, exist_ok=True)
    out.chmod(0o700)
    password = secrets.token_hex(24)
    with tempfile.TemporaryDirectory(dir=out, prefix=".making-") as tmp:    # 0700, gone with the authority's key
        work = Path(tmp)
        make_authority(work, addresses, names)
        sign_server(work, addresses, names)
        openssl(work, "pkcs12", "-export", "-name", "structr", "-inkey", "server.key", "-in", "server.crt",
                "-certfile", "ca.crt", "-out", "keystore.p12", "-passout", "env:KEYSTORE_PASSWORD",
                env={"KEYSTORE_PASSWORD": password})    # in the environment, not on the command line
        (work / "structr.env").write_text(f"STRUCTR_application_keystore_password={password}\n")
        fingerprint = openssl(work, "x509", "-in", "ca.crt", "-noout", "-fingerprint", "-sha256").strip().split("=", 1)[1]
        for name, mode in (("ca.crt", 0o644), ("structr.env", 0o600), ("keystore.p12", 0o600)):
            (work / name).chmod(mode)
            os.replace(work / name, out / name)    # the keystore last: it is what switches HTTPS on
    return fingerprint


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--host", action="append", required=True,
                        help="an IPv4 address or name other devices open; may be given again")
    parser.add_argument("--out", type=Path, default=OUT, help=argparse.SUPPRESS)
    parser.add_argument("--force", action="store_true", help="replace the certificate there")
    args = parser.parse_args(argv)
    try:
        fingerprint = make(args.out, args.host, args.force)
    except (CertError, OSError) as exc:
        print(f"problem: {exc}")
        return 1
    print(f"made {args.out}, good for {SERVER_DAYS} days, for {', '.join(args.host)}")
    print(f"authority's SHA-256 fingerprint, to compare on each device:\n  {fingerprint}")
    print("next: bash tools/owner_stack.sh up, then trust ca.crt (that file only) on each device (docs/pages.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
