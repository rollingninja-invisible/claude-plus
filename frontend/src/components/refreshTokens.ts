export const refreshTokens = async (
  axiosInstance: any,
  refreshToken: string,
  setTokens: (accessToken: string, refreshToken: string) => void,
  clearState: () => void
) => {
  try {
    const response = await axiosInstance.post(`/auth/refresh`, {
      refresh_token: refreshToken,
    });
    const data = await response.data;

    if (data.access_token) {
      // Update the tokens in the context
      setTokens(data.access_token, refreshToken);
      return data; // Return the new tokens
    } else {
      throw new Error('Failed to refresh tokens');
    }
  } catch (error) {
    console.error('Error refreshing tokens:', error);
    clearState(); // Clear tokens if refresh fails
    throw error; // Propagate the error so it can be handled elsewhere
  }
};
