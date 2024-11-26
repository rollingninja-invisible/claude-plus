import { useEffect } from 'react';
// context api
import { useAuth } from '../AuthContext';
// types
import { InitializeGuardProps } from '../types';

// ----------------------------------------------------------------------

const InitializeGuard = ({ children }: InitializeGuardProps) => {
  const { isInitialized, setTokens, setUserDetails, setUserIntialized } =
    useAuth();

  const initializeUser = () => {
    const access_token = localStorage.getItem('accessToken');
    const refresh_token = localStorage.getItem('refreshToken');
    const profile = localStorage.getItem('profile');

    access_token && refresh_token && setTokens(access_token, refresh_token);
    profile && setUserDetails(JSON.parse(profile));

    setUserIntialized();
  };

  useEffect(() => {
    !isInitialized && initializeUser();
  }, [isInitialized]);

  return children;
};

export default InitializeGuard;
