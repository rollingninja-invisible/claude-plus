import axios from 'axios';
import { refreshTokens } from './refreshTokens';

export const createAxiosInstance = (
  accessToken: string | null,
  refreshToken: string | null,
  setTokens: (accessToken: string, refreshToken: string) => void,
  clearState: () => void
) => {
  const instance = axios.create({
    baseURL: import.meta.env.VITE_API_URL,
  });

  // Request interceptor to add access token to headers
  instance.interceptors.request.use(
    (config) => {
      if (accessToken) {
        config.headers['Authorization'] = `Bearer ${accessToken}`;
      }
      return config;
    },
    (error) => {
      return Promise.reject(error);
    }
  );

  // Response interceptor to handle token refresh when the access token expires
  instance.interceptors.response.use(
    (response) => response,
    async (error) => {
      // Check if the error is due to an expired token (401 Unauthorized)
      if (error.response && error.response.status === 401) {
        try {
          if (refreshToken) {
            // Call refreshTokens with setTokens and clearState as parameters
            const data = await refreshTokens(
              instance,
              refreshToken,
              setTokens,
              clearState
            );
            const config = error.config;
            config.headers['Authorization'] = `Bearer ${data.accessToken}`;
            return axios(config); // Retry the original request with the new token
          }
        } catch (refreshError) {
          // If refresh fails, clear tokens and redirect to login
          clearState();
          window.location.href = '/'; // Or use React Router for navigation
        }
      }

      return Promise.reject(error);
    }
  );

  return instance;
};
