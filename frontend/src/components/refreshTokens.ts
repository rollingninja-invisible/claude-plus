export const refreshTokens = async (
  axiosInstance: any,
  refreshToken: string | null,
  setTokens: (accessToken: string, refreshToken: string) => void
) => {
  if (!refreshToken) return null;

  const response = await axiosInstance.post(`/auth/refresh`, {
    refresh_token: refreshToken,
  });
  const data = await response.data;

  if (data.access_token) {
    // Update the tokens in the context
    setTokens(data.access_token, refreshToken);
    return data; // Return the new tokens
  }
};
