export default {
  async fetch(request, env, ctx) {
      return new Response('Flights Worker is running.', {
            status: 200,
                  headers: { 'Content-Type': 'text/plain' },
                      });
                        },
                        };
                        
