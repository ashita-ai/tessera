import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Shell } from "@/components/layout/Shell";
import { Dashboard } from "@/pages/Dashboard";
import { Services } from "@/pages/Services";
import { Assets } from "@/pages/Assets";
import { Proposals } from "@/pages/Proposals";
import { Teams } from "@/pages/Teams";
import { AuditLog } from "@/pages/AuditLog";

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<Dashboard />} />
          <Route path="services" element={<Services />} />
          <Route path="assets" element={<Assets />} />
          <Route path="proposals" element={<Proposals />} />
          <Route path="teams" element={<Teams />} />
          <Route path="audit" element={<AuditLog />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
