import{describe,expect,it}from"vitest";
import{normalizeIdempotencyKey,validateIntake}from"../src/policy";
describe("Qudron Cloudflare intake policy",()=>{
 it("accepts bounded public research tasks",()=>expect(validateIntake({kind:"research",title:"Minya market scan",prompt:"Research public competitors in Minya."}).ok).toBe(true));
 it("rejects customer personal data and secrets",()=>{expect(validateIntake({kind:"draft",title:"Customer CV",prompt:"Create CV for user hossam@example.com"}).ok).toBe(false);expect(validateIntake({kind:"research",title:"Account",prompt:"Use this password to log in: abcdefgh"}).ok).toBe(false);});
 it("rejects unsupported task kinds",()=>expect(validateIntake({kind:"payment",title:"Pay supplier",prompt:"Send money to supplier now."}).ok).toBe(false));
 it("rejects malformed idempotency keys",()=>{expect(normalizeIdempotencyKey("order-123")).toBe("order-123");expect(normalizeIdempotencyKey("bad key")).toBe(null);expect(normalizeIdempotencyKey("x".repeat(181))).toBe(null);});
});