import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Shell } from "@/components/layout/Shell";
import { Dashboard } from "@/pages/Dashboard";
import { Repos } from "@/pages/Repos";
import { RepoDetail } from "@/pages/RepoDetail";
import { Services } from "@/pages/Services";
import { ServiceDetail } from "@/pages/ServiceDetail";
import { Assets } from "@/pages/Assets";
import { Proposals } from "@/pages/Proposals";
import { Teams } from "@/pages/Teams";
import { AuditLog } from "@/pages/AuditLog";
import { Login } from "@/pages/Login";

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="login" element={<Login />} />
        <Route element={<Shell />}>
          <Route index element={<Dashboard />} />
          <Route path="repos" element={<Repos />} />
          <Route path="repos/:id" element={<RepoDetail />} />
          <Route path="services" element={<Services />} />
          <Route path="services/:id" element={<ServiceDetail />} />
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
