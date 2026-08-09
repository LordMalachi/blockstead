import { useRole } from "../shell/role";
import { AccountAccessPanel, PasswordPanel } from "./AccountAccessPanel";

export function AccountPage() {
  const owner = useRole() === "owner";
  return <><section className="page-head"><div><p className="eyebrow">Signed-in access</p><h1>Account</h1><p>Manage your own password. The owner can also manage trusted view-only helpers.</p></div></section><PasswordPanel />{owner && <AccountAccessPanel />}</>;
}
