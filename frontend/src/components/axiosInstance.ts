import axios, { AxiosInstance } from 'axios';
import { refreshTokens } from './refreshTokens';
import { AxiosInstanceParams } from '../types';

export const createAxiosInstance = ({
  accessToken,
  refreshToken,
  setTokens,
  clearState,
  createToast,
}: AxiosInstanceParams): AxiosInstance => {
  let isRefreshing = false;
  let refreshSubscribers: ((token: string) => void)[] = [];

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
      const originalRequest = error.config;

      // Handle refresh token API failure
      if (error.request.responseURL.includes('/auth/refresh')) {
        createToast({
          title: 'Session Expired',
          description:
            'Your session has expired. Please log in again. You are being signed out.',
          status: 'error',
          duration: 5000,
          isClosable: true,
        });
        clearState();
        return Promise.reject(error);
      }

      // Check if the error is due to an expired token (401 Unauthorized)
      if (
        error.response &&
        error.response.status === 401 &&
        !originalRequest._retry
      ) {
        if (isRefreshing) {
          try {
            const token = await new Promise<string>((resolve) => {
              refreshSubscribers.push(resolve);
            });

            console.log(token);
            originalRequest.headers['Authorization'] = `Bearer ${token}`;
            return axios(originalRequest);
          } catch (err) {
            return Promise.reject(err);
          }
        }

        originalRequest._retry = true;
        isRefreshing = true;

        try {
          const data = await refreshTokens(instance, refreshToken, setTokens);

          const newAccessToken = data.access_token;
          isRefreshing = false;
          originalRequest.headers['Authorization'] = `Bearer ${newAccessToken}`;
          refreshSubscribers.forEach((callback) => callback(newAccessToken));
          refreshSubscribers = [];
          return axios(originalRequest);
        } catch (refreshError) {
          isRefreshing = false;
          createToast({
            title: 'Session Expired',
            description:
              'Your session has expired. Please log in again. You are being signed out.',
            status: 'error',
            duration: 5000,
            isClosable: true,
          });
          clearState();
          return Promise.reject(refreshError);
        }
      }

      return Promise.reject(error);
    }
  );

  return instance;
};
