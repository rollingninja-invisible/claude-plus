// context api
import { AuthProvider } from './AuthContext';
// guards
import { UserGuard, InitializeGuard } from './guards/index';
// Cladue App
import ClaudeApp from './claudeApp';
// types
const App = () => {
  return (
    <AuthProvider>
      <InitializeGuard>
        <UserGuard>
          <ClaudeApp />
        </UserGuard>
      </InitializeGuard>
    </AuthProvider>
  );
};

export default App;
