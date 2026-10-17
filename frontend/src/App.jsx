import React, { useEffect, useState } from "react";
import { AtProvider, Spinner } from "./atom";
import { bootstrap, getMode } from "./lib/api.js";
import Login from "./components/Login.jsx";
import Dashboard from "./components/Dashboard.jsx";
import CursorFollower from "./components/CursorFollower.jsx";

export default function App() {
  const [user, setUser] = useState(undefined);   // undefined = loading, null = signed out

  useEffect(() => {
    bootstrap().then((r) => setUser(r && r.user ? r.user : null)).catch(() => setUser(null));
  }, []);

  return (
    <AtProvider pigment="emerald">
      <div className="at-root at-sky pd-app">
        <CursorFollower />
        {user === undefined ? (
          <div className="pd-center"><Spinner /></div>
        ) : user ? (
          <Dashboard key={user.id || user.email} user={user} onLogout={() => setUser(null)} />
        ) : (
          <Login onLogin={setUser} mock={getMode().mockRest} />
        )}
      </div>
    </AtProvider>
  );
}
