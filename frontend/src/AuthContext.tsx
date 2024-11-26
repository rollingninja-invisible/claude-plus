import React, { createContext, useContext, useState, ReactNode } from 'react';
// types
import { ProfileType } from './types';

// Define the shape of the auth context state
interface AuthContextType {
  isInitialized: boolean | false;
  profile: ProfileType | null;
  accessToken: string | null;
  refreshToken: string | null;
  setTokens: (accessToken: string, refreshToken: string) => void;
  setUserDetails: (Profile: ProfileType) => void;
  clearState: () => void;
  setUserIntialized: () => void;
}

// Create the context with default values
const AuthContext = createContext<AuthContextType | undefined>(undefined);

// Create the AuthProvider component to wrap the app
export const AuthProvider: React.FC<{ children: ReactNode }> = ({
  children,
}) => {
  const [isInitialized, setIntialized] = useState<boolean>(false);
  const [profile, setProfile] = useState<ProfileType | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState<string | null>(null);

  // Function to set both tokens
  const setTokens = (accessToken: string, refreshToken: string) => {
    setAccessToken(accessToken);
    setRefreshToken(refreshToken);

    // persisting tokens in localStorage
    localStorage.setItem('accessToken', accessToken);
    localStorage.setItem('refreshToken', refreshToken);
  };

  const setUserDetails = (data: ProfileType) => {
    setProfile(data);
  };

  const setUserIntialized = () => {
    setIntialized(true);
  };

  // Function to clear the tokens
  const clearState = () => {
    setAccessToken(null);
    setRefreshToken(null);
    setProfile(null);
    localStorage.removeItem('accessToken');
    localStorage.removeItem('refreshToken');
    localStorage.removeItem('profile');
  };

  return (
    <AuthContext.Provider
      value={{
        isInitialized,
        profile,
        accessToken,
        refreshToken,
        setTokens,
        clearState,
        setUserDetails,
        setUserIntialized,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

// Custom hook to use the AuthContext
export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
