import { createHashRouter } from "react-router-dom";
import { fetch, portalFetch } from "../service/http";
import { getAuthToken } from "../utils/authStorage";
import { Dashboard } from "./Dashboard";
import { Login } from "./Login";
import { CommerceAdmin } from "./CommerceAdmin";
import { PortalDashboard } from "./PortalDashboard";
import { PortalLogin } from "./PortalLogin";
import { PortalRegister } from "./PortalRegister";
const fetchAdminLoader = () => {
    return fetch("/admin", {
        headers: {
            Authorization: `Bearer ${getAuthToken()}`,
        },
    });
};
const fetchPortalLoader = () => portalFetch("/portal/me");
export const router = createHashRouter([
    {
        path: "/",
        element: <Dashboard />,
        errorElement: <Login />,
        loader: fetchAdminLoader,
    },
    {
        path: "/commerce/",
        element: <CommerceAdmin />,
        errorElement: <Login />,
        loader: fetchAdminLoader,
    },
    {
        path: "/login/",
        element: <Login />,
    },
    {
        path: "/portal/",
        element: <PortalDashboard />,
        errorElement: <PortalLogin />,
        loader: fetchPortalLoader,
    },
    {
        path: "/portal/login/",
        element: <PortalLogin />,
    },
    {
        path: "/portal/register/",
        element: <PortalRegister />,
    },
]);
