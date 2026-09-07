import axios from "axios";
import { clearOrgCookie, NOT_A_MEMBER, readOrgCookie } from "@/lib/orgCookie";

const api = axios.create({
  headers: {
    "Content-Type": "application/json",
  },
});

// Add a request interceptor
api.interceptors.request.use(
  (config) => {
    // You can add authentication headers or other modifications here
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// One reload per stale cookie: the flag stops a loop when the reload
// itself answers 403 again for another reason.
const RELOAD_GUARD = "aiops.org.reloaded";

// Add a response interceptor
api.interceptors.response.use(
  (response) => {
    if (typeof window !== "undefined") {
      sessionStorage.removeItem(RELOAD_GUARD);
    }
    return response;
  },
  (error) => {
    if (
      typeof window !== "undefined" &&
      axios.isAxiosError(error) &&
      error.response?.status === 403 &&
      error.response.data?.detail === NOT_A_MEMBER &&
      readOrgCookie()
    ) {
      clearOrgCookie();
      if (!sessionStorage.getItem(RELOAD_GUARD)) {
        sessionStorage.setItem(RELOAD_GUARD, "1");
        window.location.reload();
      }
    }
    return Promise.reject(error);
  }
);

export default api;
